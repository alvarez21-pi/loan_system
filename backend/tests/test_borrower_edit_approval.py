"""Borrower edit/delete/reactivate/notes — the staging test plan from the
client-feedback request, as automated tests: every borrower change now
routes through the SAME maker-checker approval model loans already use
(models/borrower.py's BorrowerEditRequest, services/approval.py unchanged),
loan documents snapshot the borrower at issuance, deletion is soft when
there's loan history, hard only when there is none, duplicate ID/phone is a
warning not a block, ID is optional at creation and never blocks loan
issuance (a borrower with no ID is just flagged id_pending — the notes
feature is how staff record why), and notes are an append-only authored
log."""
import pytest

from models import AuditLog


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {
        "ceo": make_user("ceo"),
        "head_manager": make_user("head_manager"),
        "maker": make_user("maker"),
        "checker": make_user("checker"),
        "checker2": make_user("checker", email="checker2@example.com"),
    }
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def make_borrower(client, headers, tag="a", phone=None, with_id=True):
    payload = {"name": f"Borrower {tag}", "phone": phone or f"0700{abs(hash(tag)) % 10**6:06d}"}
    if with_id:
        payload["id_number"] = f"ID-{tag}"
        payload["id_type"] = "passport"
    resp = client.post("/api/borrowers", json=payload, headers=headers["maker"])
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["borrower"]


def make_loan_for(client, headers, borrower_id, tag="L"):
    product = client.post("/api/loan-products", json={
        "name": f"Product {tag}", "default_interest_rate": 10, "min_term_months": 1, "max_term_months": 24,
        "min_amount": 1000, "max_amount": 50_000_000,
    }, headers=headers["ceo"])
    assert product.status_code == 201, product.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower_id, "loan_product_id": product.get_json()["loan_product"]["id"],
        "principal_amount": 500_000, "interest_rate": 10, "term_months": 6, "start_date": "2026-03-10",
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()
    loan_id = loan.get_json()["loan"]["id"]
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()
    return client.get(f"/api/loans/{loan_id}", headers=headers["maker"]).get_json()["loan"]


# --------------------------------------------------------------- 1. edit + snapshot

def test_edit_does_not_apply_live_and_issued_loan_keeps_its_original_snapshot(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e1")
    loan = make_loan_for(client, headers, borrower["id"], tag="e1")
    assert loan["borrower_name_snapshot"] == borrower["name"]

    propose = client.put(
        f"/api/borrowers/{borrower['id']}", json={"name": "Renamed Borrower"}, headers=headers["maker"],
    )
    assert propose.status_code == 201, propose.get_json()
    request_id = propose.get_json()["borrower_edit_request"]["id"]

    # Live record is UNCHANGED while pending.
    still = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert still["name"] == borrower["name"]
    assert still["pending_request"]["id"] == request_id

    approve = client.post(f"/api/borrower-edit-requests/{request_id}/approve", headers=headers["checker"])
    assert approve.status_code == 200, approve.get_json()

    updated = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert updated["name"] == "Renamed Borrower"
    assert updated["pending_request"] is None

    # The ALREADY-ISSUED loan's own document still shows the ORIGINAL name —
    # the whole point of the snapshot.
    loan_after = client.get(f"/api/loans/{loan['id']}", headers=headers["maker"]).get_json()["loan"]
    assert loan_after["borrower_name_snapshot"] == borrower["name"]
    assert loan_after["borrower_name_snapshot"] != "Renamed Borrower"

    audited = AuditLog.query.filter_by(table_name="borrower_edit_request", action="APPROVED").first()
    assert audited is not None and "Renamed Borrower" in audited.details


def test_edit_on_borrower_with_no_loan_history(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e2")
    propose = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000111"}, headers=headers["maker"])
    assert propose.status_code == 201
    request_id = propose.get_json()["borrower_edit_request"]["id"]
    approve = client.post(f"/api/borrower-edit-requests/{request_id}/approve", headers=headers["checker"])
    assert approve.status_code == 200
    updated = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert updated["phone"] == "0799000111"


def test_second_pending_edit_on_the_same_borrower_is_blocked(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e3")
    first = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000222"}, headers=headers["maker"])
    assert first.status_code == 201
    second = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000333"}, headers=headers["maker"])
    assert second.status_code == 409
    assert "pending" in second.get_json()["message"].lower()


# --------------------------------------------------------------- 2. delete

def test_delete_borrower_with_loan_history_soft_deletes_and_keeps_loan_history_correct(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d1")
    loan = make_loan_for(client, headers, borrower["id"], tag="d1")

    propose = client.post(f"/api/borrowers/{borrower['id']}/propose-delete", json={"reason": "duplicate account"}, headers=headers["maker"])
    assert propose.status_code == 201, propose.get_json()
    req = propose.get_json()["borrower_edit_request"]
    assert req["action"] == "deactivate"
    approve = client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker"])
    assert approve.status_code == 200, approve.get_json()

    gone_from_active = client.get("/api/borrowers", query_string={"active_only": "true"}, headers=headers["maker"])
    assert borrower["id"] not in [b["id"] for b in gone_from_active.get_json()["borrowers"]]

    still_visible = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"])
    assert still_visible.status_code == 200
    assert still_visible.get_json()["borrower"]["is_active"] is False

    # Their existing loan's history is untouched.
    loan_after = client.get(f"/api/loans/{loan['id']}", headers=headers["maker"]).get_json()["loan"]
    assert loan_after["borrower_id"] == borrower["id"]
    assert loan_after["borrower_name_snapshot"] == borrower["name"]


def test_delete_borrower_with_no_loan_history_hard_deletes(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d2")
    propose = client.post(f"/api/borrowers/{borrower['id']}/propose-delete", json={}, headers=headers["maker"])
    assert propose.status_code == 201
    req = propose.get_json()["borrower_edit_request"]
    assert req["action"] == "hard_delete"
    approve = client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker"])
    assert approve.status_code == 200, approve.get_json()

    gone = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"])
    assert gone.status_code == 404


def test_reactivate_a_soft_deleted_borrower(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d3")
    make_loan_for(client, headers, borrower["id"], tag="d3")
    propose = client.post(f"/api/borrowers/{borrower['id']}/propose-delete", json={}, headers=headers["maker"])
    req = propose.get_json()["borrower_edit_request"]
    client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker"])

    # A checker/maker cannot reactivate — Head Manager or CEO only.
    denied = client.post(f"/api/borrowers/{borrower['id']}/reactivate", headers=headers["checker"])
    assert denied.status_code == 403

    reactivated = client.post(f"/api/borrowers/{borrower['id']}/reactivate", headers=headers["head_manager"])
    assert reactivated.status_code == 200, reactivated.get_json()
    assert reactivated.get_json()["borrower"]["is_active"] is True

    back_in_active_list = client.get("/api/borrowers", query_string={"active_only": "true"}, headers=headers["maker"])
    assert borrower["id"] in [b["id"] for b in back_in_active_list.get_json()["borrowers"]]


# --------------------------------------------------------------- 3. duplicate detection

def test_create_with_duplicate_phone_warns_but_does_not_block(client, staff):
    _, headers = staff
    first = make_borrower(client, headers, tag="p1", phone="0788111222")
    second = client.post(
        "/api/borrowers", json={"name": "Someone Else", "phone": "0788111222"}, headers=headers["maker"],
    )
    assert second.status_code == 201, second.get_json()
    body = second.get_json()
    assert "duplicate_warning" in body
    assert first["id"] in [m["id"] for m in body["duplicate_warning"]["matches"]]


def test_edit_without_changing_id_or_phone_does_not_flag_itself_as_a_duplicate(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="p2", phone="0788333444")
    propose = client.put(
        f"/api/borrowers/{borrower['id']}", json={"phone": "0788333444", "name": "Same Phone Edit"}, headers=headers["maker"],
    )
    assert propose.status_code == 201
    # "phone" didn't actually change, so it's not in the diff, so no self-match.
    assert "duplicate_warning" not in propose.get_json()
    assert "phone" not in propose.get_json()["borrower_edit_request"]["changes"]
    assert propose.get_json()["borrower_edit_request"]["changes"]["name"]["new"] == "Same Phone Edit"


# --------------------------------------------------------------- 4. optional ID

def test_borrower_with_no_id_is_flagged_pending_in_the_borrower_list(client, staff):
    """id_pending is purely informational (the list badge, and the UI's
    nudge toward adding a note) — never a gate on anything."""
    _, headers = staff
    borrower = make_borrower(client, headers, tag="i1", with_id=False)
    assert borrower["id_pending"] is True
    listed = client.get("/api/borrowers", headers=headers["maker"]).get_json()["borrowers"]
    assert next(b for b in listed if b["id"] == borrower["id"])["id_pending"] is True


def test_a_loan_can_be_issued_normally_to_an_id_pending_borrower(client, staff):
    """Corrected behaviour: missing ID was never meant to block lending —
    only to prompt staff to note why (the notes feature), never to gate
    loan issuance. Confirmed here with NO id_number set at any point."""
    _, headers = staff
    borrower = make_borrower(client, headers, tag="i2", with_id=False)
    assert borrower["id_pending"] is True

    product = client.post("/api/loan-products", json={
        "name": "No ID gate product", "default_interest_rate": 10, "min_term_months": 1, "max_term_months": 12,
    }, headers=headers["ceo"]).get_json()["loan_product"]
    issued = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"],
        "principal_amount": 100_000, "interest_rate": 10, "term_months": 6, "start_date": "2026-04-01",
    }, headers=headers["maker"])
    assert issued.status_code == 201, issued.get_json()
    # The snapshot faithfully records "no ID at issuance" rather than
    # inventing one — matches the borrower's real state at the time.
    assert issued.get_json()["loan"]["borrower_id_number_snapshot"] is None

    approved = client.post(f"/api/loans/{issued.get_json()['loan']['id']}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()


# --------------------------------------------------------------- 5. notes

def test_notes_are_timestamped_authored_and_never_overwritten(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="n1")
    first = client.post(f"/api/borrowers/{borrower['id']}/notes", json={"text": "ID still pending, following up."}, headers=headers["maker"])
    assert first.status_code == 201, first.get_json()
    second = client.post(f"/api/borrowers/{borrower['id']}/notes", json={"text": "ID received, verified in person."}, headers=headers["ceo"])
    assert second.status_code == 201

    notes = client.get(f"/api/borrowers/{borrower['id']}/notes", headers=headers["maker"]).get_json()["borrower_notes"]
    assert len(notes) == 2
    texts = {n["text"] for n in notes}
    assert texts == {"ID still pending, following up.", "ID received, verified in person."}
    for n in notes:
        assert n["author_name_snapshot"]
        assert n["created_at"]


# --------------------------------------------------------------- 6. maker-checker rule preserved

def test_maker_checker_self_approval_rules_carry_over_to_borrower_edits(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="s1")

    # A checker who PROPOSED their own edit cannot approve it (never exempt).
    propose = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0711999000"}, headers=headers["checker"])
    req = propose.get_json()["borrower_edit_request"]
    self_approve = client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker"])
    assert self_approve.status_code == 403

    # A DIFFERENT checker can.
    other_approve = client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker2"])
    assert other_approve.status_code == 200, other_approve.get_json()

    # A maker never gets to approve at all, even someone else's.
    borrower2 = make_borrower(client, headers, tag="s2")
    propose2 = client.put(f"/api/borrowers/{borrower2['id']}", json={"phone": "0711999111"}, headers=headers["maker"])
    req2 = propose2.get_json()["borrower_edit_request"]
    maker_tries = client.post(f"/api/borrower-edit-requests/{req2['id']}/approve", headers=headers["maker"])
    assert maker_tries.status_code == 403

    # CEO is exempt from self-approval (same rule as loans).
    borrower3 = make_borrower(client, headers, tag="s3")
    propose3 = client.put(f"/api/borrowers/{borrower3['id']}", json={"phone": "0711999222"}, headers=headers["ceo"])
    req3 = propose3.get_json()["borrower_edit_request"]
    ceo_self_approve = client.post(f"/api/borrower-edit-requests/{req3['id']}/approve", headers=headers["ceo"])
    assert ceo_self_approve.status_code == 200, ceo_self_approve.get_json()


# --------------------------------------------------------------- 7. audit trail

def test_audit_log_captures_propose_approve_delete_reactivate_and_notes(client, staff):
    _, headers = staff
    # A separate borrower per action — NOT because the system can't handle
    # several approved requests over one borrower's lifetime (Postgres's
    # partial unique index, migration 20261022_0030, only ever blocks a
    # SECOND *pending* one — see test_second_pending_edit_on_the_same_
    # borrower_is_blocked for that), but because sqlite (this test's DB)
    # can't express a partial/filtered unique index and falls back to a
    # plain one across the whole column, which this test's own path through
    # the API would otherwise trip over a false positive.
    edited = make_borrower(client, headers, tag="a1")
    deleted = make_borrower(client, headers, tag="a2")
    make_loan_for(client, headers, deleted["id"], tag="a2")  # has_loan_history -> soft delete, so REACTIVATE is reachable below

    client.post(f"/api/borrowers/{edited['id']}/notes", json={"text": "flagged for review"}, headers=headers["maker"])
    propose = client.put(f"/api/borrowers/{edited['id']}", json={"phone": "0722000000"}, headers=headers["maker"])
    req = propose.get_json()["borrower_edit_request"]
    client.post(f"/api/borrower-edit-requests/{req['id']}/approve", headers=headers["checker"])

    propose_del = client.post(f"/api/borrowers/{deleted['id']}/propose-delete", json={"reason": "test"}, headers=headers["maker"])
    del_req = propose_del.get_json()["borrower_edit_request"]
    client.post(f"/api/borrower-edit-requests/{del_req['id']}/approve", headers=headers["checker"])
    client.post(f"/api/borrowers/{deleted['id']}/reactivate", headers=headers["ceo"])

    borrower_actions = {
        log.action
        for log in AuditLog.query.filter(
            AuditLog.table_name == "borrowers", AuditLog.record_id.in_([edited["id"], deleted["id"]]),
        ).all()
    }
    assert {"CREATE", "ADD_NOTE", "PROPOSE_EDIT", "PROPOSE_DELETE", "REACTIVATE"}.issubset(borrower_actions)
    # The actual decisions (approving the edit, then the delete) are filed
    # under the request they decided, not the borrower directly — same
    # separation loans/penalties already have between the record itself and
    # its own approve/reject trail.
    request_actions = {
        log.action
        for log in AuditLog.query.filter_by(table_name="borrower_edit_request").all()
        if log.record_id in (req["id"], del_req["id"])
    }
    assert request_actions == {"APPROVED"}
    for log in AuditLog.query.filter(
        AuditLog.table_name.in_(["borrowers", "borrower_edit_request"]),
    ).all():
        assert log.actor_name_snapshot
        assert log.timestamp
