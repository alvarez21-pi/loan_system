"""Borrower edit/delete/reactivate/notes — the staging test plan from the
client-feedback request, as automated tests.

Both EDIT and DELETE (soft or hard) apply IMMEDIATELY now (Grace's
correction, in two rounds: edits first, then delete to match) — unlike
loans/penalties, neither goes through a Checker any more. The audit trail
still records who did what, to what, and when, exactly as before; only the
second-person approval step is gone. Loan documents snapshot the borrower
at issuance, deletion is soft when there's loan history, hard only when
there is none, duplicate ID/phone is a warning not a block, ID is optional
at creation and never blocks loan issuance (a borrower with no ID is just
flagged id_pending — the notes feature is how staff record why), and notes
are an append-only authored log.

BorrowerEditRequest/the /borrower-edit-requests approve-reject endpoints
still exist (services/approval.py unchanged) but are never written to by
anything any more — kept only so a request that was already pending from
before this change has somewhere to be resolved. No test here creates a
new one; that machinery is exercised by test_workflows.py's loan/penalty
coverage instead, which still genuinely uses it."""
import pytest

from models import AuditLog


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {
        "ceo": make_user("ceo"),
        "head_manager": make_user("head_manager"),
        "maker": make_user("maker"),
        "checker": make_user("checker"),
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

def test_edit_applies_immediately_and_issued_loan_keeps_its_original_snapshot(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e1")
    loan = make_loan_for(client, headers, borrower["id"], tag="e1")
    assert loan["borrower_name_snapshot"] == borrower["name"]

    edited = client.put(
        f"/api/borrowers/{borrower['id']}", json={"name": "Renamed Borrower"}, headers=headers["maker"],
    )
    assert edited.status_code == 200, edited.get_json()
    assert edited.get_json()["borrower"]["name"] == "Renamed Borrower"

    # No approval step at all — the live record changed right away.
    updated = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert updated["name"] == "Renamed Borrower"
    assert updated["pending_request"] is None

    # The ALREADY-ISSUED loan's own document still shows the ORIGINAL name —
    # the whole point of the snapshot.
    loan_after = client.get(f"/api/loans/{loan['id']}", headers=headers["maker"]).get_json()["loan"]
    assert loan_after["borrower_name_snapshot"] == borrower["name"]
    assert loan_after["borrower_name_snapshot"] != "Renamed Borrower"

    audited = AuditLog.query.filter_by(table_name="borrowers", record_id=borrower["id"], action="EDIT").first()
    assert audited is not None and "Renamed Borrower" in audited.details


def test_edit_on_borrower_with_no_loan_history(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e2")
    edited = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000111"}, headers=headers["maker"])
    assert edited.status_code == 200
    assert edited.get_json()["borrower"]["phone"] == "0799000111"
    updated = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert updated["phone"] == "0799000111"


def test_two_sequential_edits_both_apply_immediately_no_approval_queue(client, staff):
    """There is no 'pending edit' state any more — a second edit right
    after the first is never blocked."""
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e3")
    first = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000222"}, headers=headers["maker"])
    assert first.status_code == 200
    second = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000333"}, headers=headers["maker"])
    assert second.status_code == 200
    updated = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"]).get_json()["borrower"]
    assert updated["phone"] == "0799000333"


def test_an_edit_is_never_blocked_by_a_prior_delete_attempt(client, staff):
    """Regression for the bug this round's audit found: a leftover pending
    row used to wrongly block a later edit with a confusing 409 ("pending
    deactivate/delete request"). Delete is immediate now too, so there is
    nothing left to leave 'pending' and block anything — proven here by
    deleting-then-reactivating-then-editing the same borrower in one go."""
    _, headers = staff
    borrower = make_borrower(client, headers, tag="e4")
    make_loan_for(client, headers, borrower["id"], tag="e4")  # loan history -> deactivate (reversible), not hard delete
    deleted = client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["maker"])
    assert deleted.status_code == 200, deleted.get_json()
    client.post(f"/api/borrowers/{borrower['id']}/reactivate", headers=headers["head_manager"])
    edited = client.put(f"/api/borrowers/{borrower['id']}", json={"phone": "0799000444"}, headers=headers["maker"])
    assert edited.status_code == 200, edited.get_json()


# --------------------------------------------------------------- 2. delete (now also immediate)

def test_delete_borrower_with_loan_history_deactivates_immediately_and_keeps_loan_history_correct(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d1")
    loan = make_loan_for(client, headers, borrower["id"], tag="d1")

    deleted = client.post(f"/api/borrowers/{borrower['id']}/delete", json={"reason": "duplicate account"}, headers=headers["maker"])
    assert deleted.status_code == 200, deleted.get_json()
    assert deleted.get_json()["borrower"]["is_active"] is False

    gone_from_active = client.get("/api/borrowers", query_string={"active_only": "true"}, headers=headers["maker"])
    assert borrower["id"] not in [b["id"] for b in gone_from_active.get_json()["borrowers"]]

    still_visible = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"])
    assert still_visible.status_code == 200
    assert still_visible.get_json()["borrower"]["is_active"] is False

    # Their existing loan's history is untouched.
    loan_after = client.get(f"/api/loans/{loan['id']}", headers=headers["maker"]).get_json()["loan"]
    assert loan_after["borrower_id"] == borrower["id"]
    assert loan_after["borrower_name_snapshot"] == borrower["name"]


def test_delete_borrower_with_no_loan_history_hard_deletes_immediately(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d2")
    deleted = client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["maker"])
    assert deleted.status_code == 200, deleted.get_json()

    gone = client.get(f"/api/borrowers/{borrower['id']}", headers=headers["maker"])
    assert gone.status_code == 404


def test_deleting_an_already_deactivated_borrower_is_rejected(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d4")
    make_loan_for(client, headers, borrower["id"], tag="d4")  # loan history -> deactivate, not hard-delete
    first = client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["maker"])
    assert first.status_code == 200
    second = client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["maker"])
    assert second.status_code == 409


def test_a_checker_can_also_delete_directly_no_second_approver_needed(client, staff):
    """borrowers:manage (which both maker and checker hold) is the only
    gate now — there is no separate approver role for this any more."""
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d5")
    deleted = client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["checker"])
    assert deleted.status_code == 200, deleted.get_json()


def test_neither_a_deactivated_nor_a_hard_deleted_borrower_ever_appears_in_the_new_loan_picker(client, staff):
    """The new-loan borrower picker (frontend: loans.index.tsx) always
    calls GET /api/borrowers?active_only=true. Deletion is immediate now
    (item 4) — confirming here there's no leftover staleness: both the
    soft-deleted and the hard-deleted borrower vanish from that list the
    moment they're deleted, no approval step/delay involved any more."""
    _, headers = staff
    soft = make_borrower(client, headers, tag="pick1")
    make_loan_for(client, headers, soft["id"], tag="pick1")  # loan history -> deactivate
    hard = make_borrower(client, headers, tag="pick2")  # no loan history -> hard delete

    before = client.get("/api/borrowers", query_string={"active_only": "true"}, headers=headers["maker"]).get_json()["borrowers"]
    assert soft["id"] in [b["id"] for b in before]
    assert hard["id"] in [b["id"] for b in before]

    client.post(f"/api/borrowers/{soft['id']}/delete", json={}, headers=headers["maker"])
    client.post(f"/api/borrowers/{hard['id']}/delete", json={}, headers=headers["maker"])

    after = client.get("/api/borrowers", query_string={"active_only": "true"}, headers=headers["maker"]).get_json()["borrowers"]
    after_ids = [b["id"] for b in after]
    assert soft["id"] not in after_ids
    assert hard["id"] not in after_ids


def test_reactivate_a_soft_deleted_borrower(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="d3")
    make_loan_for(client, headers, borrower["id"], tag="d3")
    client.post(f"/api/borrowers/{borrower['id']}/delete", json={}, headers=headers["maker"])

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
    edited = client.put(
        f"/api/borrowers/{borrower['id']}", json={"phone": "0788333444", "name": "Same Phone Edit"}, headers=headers["maker"],
    )
    assert edited.status_code == 200
    # "phone" didn't actually change, so no self-match warning.
    assert "duplicate_warning" not in edited.get_json()
    assert edited.get_json()["borrower"]["name"] == "Same Phone Edit"


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


# --------------------------------------------------------------- 6. audit trail

def test_audit_log_captures_edit_delete_reactivate_and_notes(client, staff):
    _, headers = staff
    edited = make_borrower(client, headers, tag="a1")
    deleted = make_borrower(client, headers, tag="a2")
    make_loan_for(client, headers, deleted["id"], tag="a2")  # has_loan_history -> soft delete, so REACTIVATE is reachable below

    client.post(f"/api/borrowers/{edited['id']}/notes", json={"text": "flagged for review"}, headers=headers["maker"])
    edit_resp = client.put(f"/api/borrowers/{edited['id']}", json={"phone": "0722000000"}, headers=headers["maker"])
    assert edit_resp.status_code == 200, edit_resp.get_json()

    delete_resp = client.post(f"/api/borrowers/{deleted['id']}/delete", json={"reason": "test"}, headers=headers["maker"])
    assert delete_resp.status_code == 200, delete_resp.get_json()
    client.post(f"/api/borrowers/{deleted['id']}/reactivate", headers=headers["ceo"])

    borrower_actions = {
        log.action
        for log in AuditLog.query.filter(
            AuditLog.table_name == "borrowers", AuditLog.record_id.in_([edited["id"], deleted["id"]]),
        ).all()
    }
    # Both EDIT and DEACTIVATE are now applied and logged directly against
    # the borrower — no more PROPOSE_*/APPROVED pair for either.
    assert {"CREATE", "ADD_NOTE", "EDIT", "DEACTIVATE", "REACTIVATE"}.issubset(borrower_actions)
    for log in AuditLog.query.filter_by(table_name="borrowers").all():
        assert log.actor_name_snapshot
        assert log.timestamp


def test_audit_log_captures_hard_delete_before_the_row_is_gone(client, staff):
    _, headers = staff
    borrower = make_borrower(client, headers, tag="a3")
    resp = client.post(f"/api/borrowers/{borrower['id']}/delete", json={"reason": "never contacted us again"}, headers=headers["maker"])
    assert resp.status_code == 200
    audited = AuditLog.query.filter_by(table_name="borrowers", record_id=borrower["id"], action="HARD_DELETE").first()
    assert audited is not None
    assert audited.details == "never contacted us again"
    assert audited.actor_name_snapshot
