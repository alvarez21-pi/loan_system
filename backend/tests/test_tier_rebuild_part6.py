"""Part 6 checklist for the final tier + department rebuild — each item named
after the literal requirement it verifies, at the real API level."""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader
from io import BytesIO


def _borrower_and_product(client, headers, tag):
    borrower = client.post("/api/borrowers", json={"name": f"B-{tag}", "phone": "0700", "id_number": f"ID-{tag}"}, headers=headers).get_json()["borrower"]
    product = client.post("/api/loan-products", json={"name": f"P-{tag}", "default_interest_rate": 10}, headers=headers).get_json()["loan_product"]
    return borrower, product


def test_loans_credit_checker_can_approve_but_never_create_a_loan(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker", department="loans_credit")
    checker, checker_pw = make_user("checker", department="loans_credit")
    ceo_headers = auth_headers(ceo.email, ceo_pw)
    maker_headers = auth_headers(maker.email, maker_pw)
    checker_headers = auth_headers(checker.email, checker_pw)

    borrower, product = _borrower_and_product(client, ceo_headers, "chk-loan")
    # rejected even via a direct API call — hard rule, no exception
    denied = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=checker_headers)
    assert denied.status_code == 403

    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=maker_headers).get_json()["loan"]
    approved = client.post(f"/api/loans/{loan['id']}/approve", headers=checker_headers)
    assert approved.status_code == 200, approved.get_json()


def test_loans_credit_maker_can_create_but_never_approve_a_loan(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker", department="loans_credit")
    headers = auth_headers(maker.email, maker_pw)
    # loan-products are ceo/head_manager-only system config, not a maker action
    borrower, product = _borrower_and_product(client, auth_headers(ceo.email, ceo_pw), "mkr-loan")

    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers)
    assert loan.status_code == 201, loan.get_json()
    loan_id = loan.get_json()["loan"]["id"]

    denied = client.post(f"/api/loans/{loan_id}/approve", headers=headers)
    assert denied.status_code == 403


def test_any_checker_can_approve_any_loan_but_no_checker_ever_approves_leave(client, make_user, auth_headers):
    """Part 4 simplification: a checker's loan approval carries no department
    restriction at all any more — an hr-scoped checker can approve a
    loans_credit loan just fine. Leave approval, on the other hand, is never
    a checker action, in any department, under any circumstance."""
    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker", department="loans_credit")
    hr_checker, hr_pw = make_user("checker", email="hr-scope@example.com", department="hr")
    loans_checker, loans_pw = make_user("checker", email="loans-scope@example.com", department="loans_credit")
    ceo_headers = auth_headers(ceo.email, ceo_pw)
    maker_headers = auth_headers(maker.email, maker_pw)

    borrower, product = _borrower_and_product(client, ceo_headers, "scope")
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=maker_headers).get_json()["loan"]
    assert client.post(f"/api/loans/{loan['id']}/approve", headers=auth_headers(hr_checker.email, hr_pw)).status_code == 200

    from extensions import db
    from models import Employee
    employee = Employee(name="Someone", job_title="Officer", salary=Decimal("0"), phone="0733111222", start_date=date.today(), is_active=True)
    db.session.add(employee)
    db.session.commit()
    leave = client.post("/api/leave-requests", json={
        "employee_id": employee.id, "leave_type": "Annual", "start_date": "2026-03-01", "end_date": "2026-03-02",
    }, headers=ceo_headers).get_json()["leave_request"]
    assert client.post(f"/api/leave-requests/{leave['id']}/approve", headers=auth_headers(loans_checker.email, loans_pw)).status_code == 403


def test_department_manager_can_approve_own_loan_checker_and_maker_cannot(client, make_user, auth_headers):
    department_manager, dm_pw = make_user("department_manager", department="loans_credit")
    checker, checker_pw = make_user("checker", department="loans_credit")
    maker, maker_pw = make_user("maker", department="loans_credit")
    dm_headers = auth_headers(department_manager.email, dm_pw)

    from extensions import db
    from models import Borrower, Loan, LoanProduct

    def bare_loan(creator_id, tag):
        borrower = Borrower(name=f"Self-{tag}", phone="0711", id_type="nida", id_number=f"SELF-{tag}")
        product = LoanProduct(name=f"SelfP-{tag}", default_interest_rate=10, is_active=True)
        db.session.add_all([borrower, product])
        db.session.commit()
        loan = Loan(
            borrower_id=borrower.id, loan_product_id=product.id, principal_amount=Decimal("50000"),
            interest_rate=10, term_months=6, start_date=date(2026, 1, 1), status="pending_approval",
            outstanding_balance=Decimal("50000"), created_by=creator_id,
        )
        db.session.add(loan)
        db.session.commit()
        return loan.id

    dm_loan_id = bare_loan(department_manager.id, "dm")
    checker_loan_id = bare_loan(checker.id, "chk")
    maker_loan_id = bare_loan(maker.id, "mkr")

    assert client.post(f"/api/loans/{dm_loan_id}/approve", headers=dm_headers).status_code == 200
    assert client.post(f"/api/loans/{checker_loan_id}/approve", headers=auth_headers(checker.email, checker_pw)).status_code == 403
    assert client.post(f"/api/loans/{maker_loan_id}/approve", headers=auth_headers(maker.email, maker_pw)).status_code == 403


def test_only_ceo_creates_a_head_manager_a_head_manager_cannot_create_a_second_one(client, make_user, auth_headers):
    head_manager, hm_pw = make_user("head_manager")
    denied = client.post(
        "/api/auth/register",
        json={"name": "X", "email": "hm-denied@example.com", "phone": "0700555001", "role": "head_manager"},
        headers=auth_headers(head_manager.email, hm_pw),
    )
    assert denied.status_code == 403

    ceo, ceo_pw = make_user("ceo")
    allowed = client.post(
        "/api/auth/register",
        json={"name": "X", "email": "hm-allowed@example.com", "phone": "0700555002", "role": "head_manager"},
        headers=auth_headers(ceo.email, ceo_pw),
    )
    assert allowed.status_code == 201


def test_nobody_can_deactivate_or_edit_a_ceo_account(client, make_user, auth_headers):
    ceo, _ = make_user("ceo")
    other_ceo, other_pw = make_user("ceo", email="other-ceo@example.com")
    head_manager, hm_pw = make_user("head_manager")
    department_manager, dm_pw = make_user("department_manager", department="hr")

    for actor_email, actor_pw in ((other_ceo.email, other_pw), (head_manager.email, hm_pw), (department_manager.email, dm_pw)):
        headers = auth_headers(actor_email, actor_pw)
        assert client.patch(f"/api/users/{ceo.id}", json={"is_active": False}, headers=headers).status_code == 403
        assert client.patch(f"/api/users/{ceo.id}", json={"department": "hr"}, headers=headers).status_code == 403
        assert client.delete(f"/api/users/{ceo.id}", headers=headers).status_code == 403


def test_capital_summary_returns_outstanding_balance_and_total_disbursed_as_distinct_fields(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker", department="loans_credit")
    checker, checker_pw = make_user("checker", department="loans_credit")
    ceo_headers = auth_headers(ceo.email, ceo_pw)

    client.post("/api/capital/opening", json={"new_value": 1_000_000}, headers=ceo_headers)
    borrower, product = _borrower_and_product(client, ceo_headers, "cap")
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 200_000,
        "interest_rate": 10, "term_months": 12, "start_date": "2026-01-01",
    }, headers=auth_headers(maker.email, maker_pw)).get_json()["loan"]
    approved = client.post(f"/api/loans/{loan['id']}/approve", headers=auth_headers(checker.email, checker_pw))
    assert approved.status_code == 200, approved.get_json()

    body = client.get("/api/capital/summary", headers=ceo_headers).get_json()
    assert "outstanding_balance" in body and "total_disbursed" in body
    assert body["outstanding_balance"] == 200_000
    assert body["total_disbursed"] == 200_000
    # distinct fields — a repayment moves one, not the other. (First month's
    # interest alone is 20,000 at 10%; pay well past that so principal moves too.)
    repaid = client.post("/api/repayments", json={"loan_id": loan["id"], "amount_paid": 50_000, "payment_date": "2026-01-01"}, headers=auth_headers(maker.email, maker_pw))
    assert repaid.status_code == 201, repaid.get_json()
    after = client.get("/api/capital/summary", headers=ceo_headers).get_json()
    assert after["total_disbursed"] == 200_000  # lifetime figure, unchanged by a repayment
    assert after["outstanding_balance"] < 200_000  # live balance, reduced


def test_schedule_endpoints_and_pdf_drop_the_rate_summary_line_but_keep_the_totals_row(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker", department="loans_credit")
    headers = auth_headers(maker.email, maker_pw)
    borrower, product = _borrower_and_product(client, auth_headers(ceo.email, ceo_pw), "sched")

    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 100_000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers).get_json()["loan"]

    detail = client.get(f"/api/loans/{loan['id']}", headers=headers).get_json()["loan"]
    assert "totals" in detail
    assert {"total_principal", "total_interest", "total_payable"} <= set(detail["totals"])

    preview = client.post("/api/loan-calculator/preview", json={
        "principal": 100_000, "interest_rate": 10, "term_months": 6, "interest_type": "reducing_balance",
    }, headers=headers).get_json()
    assert {"total_principal", "total_interest", "total_payable"} <= set(preview["totals"])

    pdf = client.get(f"/api/loans/{loan['id']}/schedule/export", headers=headers)
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf"
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf.data)).pages)
    assert "Totals" in text  # the totals row is still there
    assert "EMI" not in text  # the removed standalone rate/EMI summary line is gone
