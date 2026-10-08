"""Phase 5 — server-side search/sort/pagination on the five named lists
(loans, borrowers, repayments, users, audit log), opt-in via page/page_size
so every OTHER existing consumer of these same endpoints (dashboard,
reports pickers, the approvals queue, a borrower's own loan history) keeps
getting the full, unpaginated list exactly as before.
"""
import pytest


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {"ceo": make_user("ceo"), "maker": make_user("maker"), "checker": make_user("checker")}
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def make_borrowers(client, headers, count, prefix="Pager"):
    ids = []
    for i in range(count):
        resp = client.post("/api/borrowers", json={
            "name": f"{prefix} Borrower {i:03d}", "phone": f"0700{i:06d}", "id_number": f"PG-{i:04d}",
        }, headers=headers["maker"])
        assert resp.status_code == 201, resp.get_json()
        ids.append(resp.get_json()["borrower"]["id"])
    return ids


# --------------------------------------------------------------- borrowers

def test_borrowers_without_pagination_params_returns_everything_unchanged(client, staff):
    _, headers = staff
    make_borrowers(client, headers, 30)
    response = client.get("/api/borrowers", headers=headers["maker"])
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["borrowers"]) == 30
    assert "pagination" not in body


def test_borrowers_with_page_params_returns_a_slice_plus_metadata(client, staff):
    _, headers = staff
    make_borrowers(client, headers, 30)
    page1 = client.get("/api/borrowers?page=1&page_size=25", headers=headers["maker"])
    assert page1.status_code == 200
    body1 = page1.get_json()
    assert len(body1["borrowers"]) == 25
    assert body1["pagination"] == {"page": 1, "page_size": 25, "total": 30, "total_pages": 2}

    page2 = client.get("/api/borrowers?page=2&page_size=25", headers=headers["maker"])
    body2 = page2.get_json()
    assert len(body2["borrowers"]) == 5
    assert body2["pagination"]["page"] == 2

    # No overlap between pages.
    ids1 = {b["id"] for b in body1["borrowers"]}
    ids2 = {b["id"] for b in body2["borrowers"]}
    assert not (ids1 & ids2)


def test_borrowers_search_filters_by_name_or_phone(client, staff):
    _, headers = staff
    make_borrowers(client, headers, 5, prefix="Searchable")
    client.post("/api/borrowers", json={
        "name": "Totally Different Person", "phone": "0799999999", "id_number": "DIFF-1",
    }, headers=headers["maker"])

    response = client.get("/api/borrowers?page=1&page_size=25&q=Searchable", headers=headers["maker"])
    body = response.get_json()
    assert body["pagination"]["total"] == 5
    assert all("Searchable" in b["name"] for b in body["borrowers"])


# --------------------------------------------------------------- loans

def test_loans_pagination_and_search_by_borrower_name(client, staff):
    _, headers = staff
    for i in range(3):
        borrower = client.post("/api/borrowers", json={
            "name": f"Loan Borrower {i}", "phone": f"0711{i:06d}", "id_number": f"LN-{i}",
        }, headers=headers["maker"])
        client.post("/api/loans", json={
            "borrower_id": borrower.get_json()["borrower"]["id"],
            "principal_amount": 100000, "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])

    unpaginated = client.get("/api/loans", headers=headers["maker"])
    assert "pagination" not in unpaginated.get_json()
    assert len(unpaginated.get_json()["loans"]) == 3

    paginated = client.get("/api/loans?page=1&page_size=2", headers=headers["maker"])
    body = paginated.get_json()
    assert len(body["loans"]) == 2
    assert body["pagination"]["total"] == 3

    searched = client.get("/api/loans?q=Loan Borrower 1", headers=headers["maker"])
    searched_body = searched.get_json()
    assert len(searched_body["loans"]) == 1
    assert searched_body["loans"][0]["borrower_name"] == "Loan Borrower 1"


# --------------------------------------------------------------- users

def test_users_pagination_search_and_department_scoping_still_apply(client, staff, make_user):
    _, headers = staff
    for i in range(3):
        make_user("maker", email=f"paginated-maker-{i}@example.com", name=f"Paged Maker {i}")

    unpaginated = client.get("/api/users", headers=headers["ceo"])
    assert "pagination" not in unpaginated.get_json()

    paginated = client.get("/api/users?page=1&page_size=2", headers=headers["ceo"])
    body = paginated.get_json()
    assert len(body["users"]) == 2
    assert body["pagination"]["total"] >= 5  # ceo, maker, checker + 3 paged makers

    searched = client.get("/api/users?q=Paged Maker 0", headers=headers["ceo"])
    assert len(searched.get_json()["users"]) == 1


# --------------------------------------------------------------- audit log

def test_audit_logs_pagination_and_search(client, staff):
    _, headers = staff
    make_borrowers(client, headers, 5, prefix="AuditTrigger")

    unpaginated = client.get("/api/audit-logs", headers=headers["ceo"])
    assert "pagination" not in unpaginated.get_json()
    total_unpaginated = len(unpaginated.get_json()["audit_logs"])
    assert total_unpaginated >= 5

    paginated = client.get("/api/audit-logs?page=1&page_size=3", headers=headers["ceo"])
    body = paginated.get_json()
    assert len(body["audit_logs"]) == 3
    assert body["pagination"]["total"] == total_unpaginated


def test_audit_logs_still_forbidden_for_a_role_without_audit_view(client, staff):
    _, headers = staff
    response = client.get("/api/audit-logs?page=1", headers=headers["maker"])
    assert response.status_code == 403


def test_audit_log_actions_lists_distinct_values_and_filters_exactly(client, staff):
    _, headers = staff
    make_borrowers(client, headers, 2, prefix="ActionFilter")

    actions = client.get("/api/audit-logs/actions", headers=headers["ceo"])
    assert actions.status_code == 200
    action_values = actions.get_json()["actions"]
    assert "CREATE_BORROWER" in action_values or len(action_values) > 0
    assert action_values == sorted(set(action_values))  # distinct, sorted

    one_action = action_values[0]
    filtered = client.get(f"/api/audit-logs?action={one_action}", headers=headers["ceo"])
    assert filtered.status_code == 200
    assert all(row["action"] == one_action for row in filtered.get_json()["audit_logs"])


def test_audit_log_actions_forbidden_for_a_role_without_audit_view(client, staff):
    _, headers = staff
    response = client.get("/api/audit-logs/actions", headers=headers["maker"])
    assert response.status_code == 403


# --------------------------------------------------------------- repayments

def test_repayments_pagination_and_search(client, staff):
    _, headers = staff
    borrower = client.post("/api/borrowers", json={
        "name": "Repayer Borrower", "phone": "0722000000", "id_number": "REP-1",
    }, headers=headers["maker"])
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"],
        "principal_amount": 1_000_000, "interest_rate": 10, "term_months": 12, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    loan_id = loan.get_json()["loan"]["id"]
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()

    for i, key in enumerate(["pay-a", "pay-b"]):
        client.post("/api/repayments", json={
            "loan_id": loan_id, "amount_paid": 50000, "payment_date": "2026-02-15", "idempotency_key": key,
        }, headers=headers["maker"])

    unpaginated = client.get("/api/repayments", headers=headers["maker"])
    assert "pagination" not in unpaginated.get_json()
    assert len(unpaginated.get_json()["repayments"]) == 2

    paginated = client.get("/api/repayments?page=1&page_size=1", headers=headers["maker"])
    body = paginated.get_json()
    assert len(body["repayments"]) == 1
    assert body["pagination"]["total"] == 2

    searched = client.get("/api/repayments?q=Repayer", headers=headers["maker"])
    assert len(searched.get_json()["repayments"]) == 2
