"""Phase 2 item 6: the backend is the only source of the settlement figure.
GET /api/loans/<id>'s settlement_amount (routes/resources.py's
settlement_amount()) and POST /api/loans/<id>/settle's breakdown.total_to_settle
(routes/operations.py's settle_loan(), discount=0) must always agree — the
frontend (RepaymentForm.tsx's SettleLoanPanel) only ever displays one or the
other, never re-deriving it from outstanding_balance + interest_portion
itself.
"""
from decimal import Decimal

import pytest


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {"ceo": make_user("ceo"), "maker": make_user("maker"), "checker": make_user("checker")}
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def create_active_loan(client, headers, principal=1_000_000, rate=12, term=8, start="2026-01-01", tag="a"):
    borrower = client.post("/api/borrowers", json={
        "name": f"Settle Borrower {tag}", "phone": f"0700{tag}", "id_number": f"SET-{tag}",
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


def test_settle_breakdown_matches_the_loans_settlement_amount_field(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="s1")
    loan = get_loan(client, headers, loan_id)
    quoted_settlement = Decimal(str(loan["settlement_amount"]))
    # Sanity: this is exactly outstanding_balance + the open row's interest —
    # the one settlement formula, computed once (routes/operations.py's
    # settlement_amount()), never duplicated client-side.
    open_row = next(r for r in loan["schedules"] if r["status"] in ("upcoming", "partial", "missed"))
    assert quoted_settlement == Decimal(str(loan["outstanding_balance"])) + Decimal(str(open_row["interest_portion"]))

    settled = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": "2026-01-20", "idempotency_key": "settle-consistency-1",
    }, headers=headers["maker"])
    assert settled.status_code == 201, settled.get_json()
    breakdown = settled.get_json()["breakdown"]
    assert Decimal(str(breakdown["total_to_settle"])) == quoted_settlement
    assert get_loan(client, headers, loan_id)["status"] == "closed"


def test_settle_breakdown_with_a_partial_payment_first_still_matches(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="s2")
    loan = get_loan(client, headers, loan_id)
    due_date = loan["schedules"][0]["due_date"]

    partial = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 50000, "payment_date": due_date, "idempotency_key": "partial-1",
    }, headers=headers["maker"])
    assert partial.status_code == 201, partial.get_json()

    loan = get_loan(client, headers, loan_id)
    quoted_settlement = Decimal(str(loan["settlement_amount"]))

    settled = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": due_date, "idempotency_key": "settle-consistency-2",
    }, headers=headers["maker"])
    assert settled.status_code == 201, settled.get_json()
    assert Decimal(str(settled.get_json()["breakdown"]["total_to_settle"])) == quoted_settlement
