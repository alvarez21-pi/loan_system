"""Cash Flow statement (routes/reports.py cash_flow): capital injections/
withdrawals under Financing Activities (reusing the existing CapitalEntry
mechanism — no new table), correct Net Change, and the statement's section
structure (Operating Activities / Financing Activities / Opening & Closing
Balance), including that it reconciles: Opening + Net Change == Closing."""
from decimal import Decimal

import pytest


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {
        "ceo": make_user("ceo"),
        "maker": make_user("maker"),
        "checker": make_user("checker"),
    }
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def test_capital_injection_appears_under_financing_activities_with_correct_net(client, staff):
    _, headers = staff
    maker, checker, ceo = headers["maker"], headers["checker"], headers["ceo"]

    # Operating activity: a loan disbursed in the period (cash out).
    borrower = client.post("/api/borrowers", json={
        "name": "Cash Flow Borrower", "phone": "0711222333", "id_number": "ID-CF1", "nida_number": "NIDA-CF1",
    }, headers=maker)
    assert borrower.status_code == 201, borrower.get_json()
    product = client.post("/api/loan-products", json={
        "name": "Cash Flow Product", "default_interest_rate": 10, "min_term_months": 1, "max_term_months": 24,
        "min_amount": 1000, "max_amount": 50_000_000,
    }, headers=ceo)
    assert product.status_code == 201, product.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"], "loan_product_id": product.get_json()["loan_product"]["id"],
        "principal_amount": 500_000, "interest_rate": 10, "term_months": 6, "start_date": "2026-03-10",
    }, headers=maker)
    assert loan.status_code == 201, loan.get_json()
    approved = client.post(f"/api/loans/{loan.get_json()['loan']['id']}/approve", headers=checker)
    assert approved.status_code == 200, approved.get_json()

    # Operating activity: an expense (cash out).
    expense = client.post("/api/expenses", json={
        "description": "Office rent", "category": "Rent", "amount": 100_000, "date": "2026-03-12",
    }, headers=ceo)
    assert expense.status_code == 201, expense.get_json()

    # Financing activity: the owner injects fresh capital (cash in) — this
    # is the exact scenario that used to make Net look misleadingly
    # negative, since the loan disbursed FROM it had no offsetting inflow
    # anywhere in the report.
    injection = client.post("/api/capital/injections", json={
        "amount": 1_000_000, "date": "2026-03-05", "note": "Owner capital injection",
    }, headers=ceo)
    assert injection.status_code == 201, injection.get_json()

    response = client.get(
        "/api/reports/cash-flow", query_string={"start_date": "2026-03-01", "end_date": "2026-03-31"}, headers=ceo,
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()

    # 1) The capital injection shows up, tagged Financing, with the right sign/amount.
    financing_rows = [r for r in body["flow"] if r["section"] == "Financing"]
    assert len(financing_rows) == 1
    assert financing_rows[0]["description"] == "Capital injection"
    assert financing_rows[0]["amount"] == 1_000_000.0

    # 2) Operating activities (loan disbursed + expense) are tagged Operating and negative.
    operating_rows = {r["description"]: r["amount"] for r in body["flow"] if r["section"] == "Operating"}
    assert any(desc.endswith("disbursed") and amt == -500_000.0 for desc, amt in operating_rows.items())
    assert operating_rows["Expense: Rent"] == -100_000.0

    # 3) Net totals are correct, and NOT misleadingly negative — the
    # injection offsets the disbursement+expense within the same period.
    assert body["operating_activities_net"] == -600_000.0
    assert body["financing_activities_net"] == 1_000_000.0
    assert body["net_change_in_cash"] == 400_000.0

    # 4) Opening + Net Change == Closing, exactly (the statement reconciles).
    opening = Decimal(str(body["opening_balance"]))
    net_change = Decimal(str(body["net_change_in_cash"]))
    closing = Decimal(str(body["closing_balance"]))
    assert opening + net_change == closing


def test_cash_flow_pdf_export_has_the_statement_sections(client, staff):
    """Smoke test for the PDF path: section_rows/subtotal_rows indexes must
    not be out of range, and the response must actually be a PDF."""
    _, headers = staff
    ceo = headers["ceo"]
    client.post("/api/capital/injections", json={
        "amount": 250_000, "date": "2026-04-05", "note": "test",
    }, headers=ceo)
    client.post("/api/capital/withdrawals", json={
        "amount": 50_000, "date": "2026-04-10", "note": "owner draw",
    }, headers=ceo)

    response = client.get(
        "/api/reports/cash-flow",
        query_string={"start_date": "2026-04-01", "end_date": "2026-04-30", "format": "pdf"},
        headers=ceo,
    )
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data[:4] == b"%PDF"


def test_cash_flow_excel_export_has_the_statement_sections(client, staff):
    _, headers = staff
    ceo = headers["ceo"]
    client.post("/api/capital/injections", json={
        "amount": 250_000, "date": "2026-05-05", "note": "test",
    }, headers=ceo)

    response = client.get(
        "/api/reports/cash-flow",
        query_string={"start_date": "2026-05-01", "end_date": "2026-05-31", "format": "excel"},
        headers=ceo,
    )
    assert response.status_code == 200
    assert response.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_cash_flow_with_no_activity_still_reconciles_opening_to_closing(client, staff):
    """No transactions in the period at all: Net Change is zero, and
    Opening Balance must equal Closing Balance exactly."""
    _, headers = staff
    ceo = headers["ceo"]
    response = client.get(
        "/api/reports/cash-flow", query_string={"start_date": "2026-06-01", "end_date": "2026-06-30"}, headers=ceo,
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["net_change_in_cash"] == 0.0
    assert body["opening_balance"] == body["closing_balance"]
    assert body["flow"] == []
