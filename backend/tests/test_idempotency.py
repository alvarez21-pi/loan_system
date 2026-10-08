"""Phase 2 item 5: repayments carry an optional, unique idempotency_key so a
double-click or a retried request for the SAME submission can never record
the same payment twice. The real frontend (RepaymentForm.tsx) always sends
one; a caller that doesn't is unaffected (backward compatible with every
existing direct-API test)."""
from decimal import Decimal

import pytest


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {"ceo": make_user("ceo"), "maker": make_user("maker"), "checker": make_user("checker")}
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def create_active_loan(client, headers, principal=1_000_000, rate=10, term=6, start="2026-01-01", tag="a"):
    borrower = client.post("/api/borrowers", json={
        "name": f"Idem Borrower {tag}", "phone": f"0700{tag}", "id_number": f"IDEM-{tag}",
    }, headers=headers["maker"])
    assert borrower.status_code == 201, borrower.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"],
        "principal_amount": principal, "interest_rate": rate, "term_months": term, "start_date": start,
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()
    loan_id = loan.get_json()["loan"]["id"]
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()
    return loan_id


def get_loan(client, headers, loan_id):
    response = client.get(f"/api/loans/{loan_id}", headers=headers["maker"])
    assert response.status_code == 200
    return response.get_json()["loan"]


def test_repeating_a_repayment_with_the_same_key_does_not_double_charge(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="r1")
    loan = get_loan(client, headers, loan_id)
    due_date = loan["schedules"][0]["due_date"]
    payload = {"loan_id": loan_id, "amount_paid": 400000, "payment_date": due_date, "idempotency_key": "submit-key-1"}

    first = client.post("/api/repayments", json=payload, headers=headers["maker"])
    assert first.status_code == 201, first.get_json()

    # Simulates a double-click / network retry resending the exact same
    # submission (same key, same body).
    second = client.post("/api/repayments", json=payload, headers=headers["maker"])
    assert second.status_code == 200, second.get_json()
    assert second.get_json()["replay"] is True
    assert second.get_json()["repayment"]["id"] == first.get_json()["repayment"]["id"]

    final = get_loan(client, headers, loan_id)
    # Only ONE payment's worth of principal was ever deducted.
    assert Decimal(str(final["outstanding_balance"])) == Decimal(str(first.get_json()["loan"]["outstanding_balance"]))


def test_repeating_a_settlement_with_the_same_key_does_not_double_charge(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="r2")
    payload = {"payment_date": "2026-02-01", "idempotency_key": "settle-key-1"}

    first = client.post(f"/api/loans/{loan_id}/settle", json=payload, headers=headers["maker"])
    assert first.status_code == 201, first.get_json()
    assert get_loan(client, headers, loan_id)["status"] == "closed"

    second = client.post(f"/api/loans/{loan_id}/settle", json=payload, headers=headers["maker"])
    assert second.status_code == 200, second.get_json()
    assert second.get_json()["replay"] is True
    assert second.get_json()["repayment"]["id"] == first.get_json()["repayment"]["id"]


def test_two_submissions_with_different_keys_are_both_recorded(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="r3")
    loan = get_loan(client, headers, loan_id)
    due_date = loan["schedules"][0]["due_date"]

    first = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 100000, "payment_date": due_date, "idempotency_key": "key-a",
    }, headers=headers["maker"])
    assert first.status_code == 201, first.get_json()
    second = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 50000, "payment_date": due_date, "idempotency_key": "key-b",
    }, headers=headers["maker"])
    assert second.status_code == 201, second.get_json()
    assert first.get_json()["repayment"]["id"] != second.get_json()["repayment"]["id"]


def test_omitting_the_idempotency_key_still_works_for_backward_compatibility(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="r4")
    loan = get_loan(client, headers, loan_id)
    due_date = loan["schedules"][0]["due_date"]

    first = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 100000, "payment_date": due_date,
    }, headers=headers["maker"])
    assert first.status_code == 201, first.get_json()
    second = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 50000, "payment_date": due_date,
    }, headers=headers["maker"])
    assert second.status_code == 201, second.get_json()
