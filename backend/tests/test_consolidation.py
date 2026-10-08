from datetime import date
from decimal import Decimal

from itsdangerous import URLSafeTimedSerializer


def _make_loan(app, db, maker_id, principal=Decimal("100000"), status="active"):
    from models import Borrower, Loan, LoanProduct

    borrower = Borrower(name="Jane Borrower", phone="0711000000", id_type="nida", id_number=f"ID-{maker_id}-{status}")
    product = LoanProduct(
        name=f"Product-{maker_id}-{status}", default_interest_rate=10, min_term_months=1, max_term_months=24,
        min_amount=1000, max_amount=1000000, is_active=True,
    )
    db.session.add_all([borrower, product])
    db.session.commit()
    loan = Loan(
        borrower_id=borrower.id, loan_product_id=product.id, principal_amount=principal,
        interest_rate=10, term_months=12, start_date=date(2026, 1, 1),
        status=status, outstanding_balance=principal, created_by=maker_id,
    )
    db.session.add(loan)
    db.session.commit()
    return loan.id


# ---------------------------------------------------------------- money validation


def test_negative_and_non_numeric_amounts_rejected(client, make_user, auth_headers, app):
    from extensions import db

    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker")
    maker_headers = auth_headers(maker.email, maker_pw)
    ceo_headers = auth_headers(ceo.email, ceo_pw)

    with app.app_context():
        from models import Borrower, LoanProduct

        borrower = Borrower(name="B", phone="0700", id_type="nida", id_number="ID-NEG")
        product = LoanProduct(name="NegProduct", default_interest_rate=10, min_term_months=1, max_term_months=24, min_amount=1, max_amount=1000000, is_active=True)
        db.session.add_all([borrower, product])
        db.session.commit()
        borrower_id, product_id = borrower.id, product.id

    resp = client.post(
        "/api/loans",
        json={"borrower_id": borrower_id, "loan_product_id": product_id, "principal_amount": -1000, "interest_rate": 10, "term_months": 12, "start_date": "2026-01-01"},
        headers=maker_headers,
    )
    assert resp.status_code == 400

    # expenses:manage is not in the maker template (Part 1.1) — use ceo here.
    resp = client.post("/api/expenses", json={"description": "x", "category": "Other", "amount": -5, "date": "2026-01-01"}, headers=ceo_headers)
    assert resp.status_code == 400

    resp = client.post("/api/expenses", json={"description": "x", "category": "Other", "amount": "not-a-number", "date": "2026-01-01"}, headers=ceo_headers)
    assert resp.status_code == 400

    resp = client.post("/api/assets", json={"name": "x", "type": "y", "value": -5, "date_acquired": "2026-01-01"}, headers=ceo_headers)
    assert resp.status_code == 400

    resp = client.post(
        "/api/employees",
        json={"name": "x", "phone": "0700111222", "job_title": "Teller", "salary": -100, "start_date": "2026-01-01"},
        headers=ceo_headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------- checker create lockdown


def test_checker_can_create_borrowers_and_penalties_but_never_a_loan(client, make_user, auth_headers):
    """A real change from the previous model: a checker can now create
    borrowers/repayments/expenses/penalties directly, same as a maker — but
    the hard rule stands, no exception: a checker can never create a loan,
    and loan-products/assets/employees/payroll stay out of reach entirely."""
    checker, checker_pw = make_user("checker", department="loans_credit")
    headers = auth_headers(checker.email, checker_pw)

    borrower = client.post("/api/borrowers", json={"name": "B", "phone": "0700", "id_number": "IDX"}, headers=headers)
    assert borrower.status_code == 201, borrower.get_json()

    # never a loan — even via direct API call, hard rule, no exception
    loan_product = client.post("/api/loan-products", json={"name": "P", "default_interest_rate": 10}, headers=headers)
    assert loan_product.status_code == 403
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"], "loan_product_id": 999999,
        "principal_amount": 1000, "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers)
    assert loan.status_code == 403

    forbidden = [
        ("/api/assets", {"name": "x", "type": "y", "value": 5, "date_acquired": "2026-01-01"}),
        ("/api/employees", {"name": "x", "phone": "0700111", "job_title": "Teller", "salary": 100, "start_date": "2026-01-01"}),
        ("/api/payroll", {"month": "2026-01"}),
    ]
    for path, body in forbidden:
        resp = client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, f"{path} should be forbidden for checker, got {resp.status_code}"


def test_checker_can_only_request_own_leave(client, make_user, auth_headers, app):
    from extensions import db
    from models import Employee

    checker, checker_pw = make_user("checker")
    other_checker, _ = make_user("checker", email="other-checker@example.com")
    headers = auth_headers(checker.email, checker_pw)

    with app.app_context():
        own_employee = Employee(name=checker.name, job_title="Teller", salary=Decimal("0"), phone=checker.phone, start_date=date.today(), is_active=True, user_id=checker.id)
        other_employee = Employee(name=other_checker.name, job_title="Teller", salary=Decimal("0"), phone=other_checker.phone, start_date=date.today(), is_active=True, user_id=other_checker.id)
        db.session.add_all([own_employee, other_employee])
        db.session.commit()
        own_id, other_id = own_employee.id, other_employee.id

    resp = client.post(
        "/api/leave-requests",
        json={"employee_id": other_id, "leave_type": "Annual", "start_date": "2026-02-01", "end_date": "2026-02-05"},
        headers=headers,
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/leave-requests",
        json={"employee_id": own_id, "leave_type": "Annual", "start_date": "2026-02-01", "end_date": "2026-02-05"},
        headers=headers,
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------- token-only verification page


def test_password_reset_confirm_ignores_a_different_users_active_session(client, make_user, auth_headers, app):
    ceo, ceo_pw = make_user("ceo")
    target, _ = make_user("maker", email="target-reset@example.com")

    with app.app_context():
        serializer = URLSafeTimedSerializer(app.config["JWT_SECRET_KEY"], salt="loan-system-password-reset")
        token = serializer.dumps({"user_id": target.id, "purpose": "password_reset", "v": target.credentials_version})

    # The CEO is logged in elsewhere in the same browser — their bearer token
    # is attached anyway. The endpoint must ignore it entirely and act purely
    # on the reset token in the body.
    someone_elses_session = auth_headers(ceo.email, ceo_pw)
    response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "password": "BrandNewPassw0rd!"},
        headers=someone_elses_session,
    )
    assert response.status_code == 200

    login_response = client.post("/api/auth/login", json={"email": target.email, "password": "BrandNewPassw0rd!"})
    assert login_response.status_code == 200
    assert login_response.get_json()["user"]["id"] == target.id


# ---------------------------------------------------------------- penalty reversal


def test_penalty_reversal_reverses_the_balance_change(client, make_user, auth_headers, app):
    """Penalty approval/reversal is department_manager-and-above now (a
    checker no longer holds penalties:approve at all under the tier model)."""
    from extensions import db
    from models import Loan, Penalty

    ceo, ceo_pw = make_user("ceo")
    maker, maker_pw = make_user("maker")
    department_manager, department_manager_pw = make_user("department_manager", department="loans_credit")

    with app.app_context():
        loan_id = _make_loan(app, db, maker.id, principal=Decimal("100000"))

    maker_headers = auth_headers(maker.email, maker_pw)
    department_manager_headers = auth_headers(department_manager.email, department_manager_pw)
    ceo_headers = auth_headers(ceo.email, ceo_pw)

    resp = client.post("/api/penalties", json={"loan_id": loan_id, "amount": 5000, "reason": "late payment"}, headers=maker_headers)
    assert resp.status_code == 201
    penalty_id = resp.get_json()["penalty"]["id"]

    resp = client.post(f"/api/penalties/{penalty_id}/approve", headers=department_manager_headers)
    assert resp.status_code == 200

    with app.app_context():
        assert Loan.query.get(loan_id).outstanding_balance == Decimal("105000.00")

    # the original approver cannot reverse their own approval
    resp = client.post(f"/api/penalties/{penalty_id}/reverse", json={"reason": "mistake"}, headers=department_manager_headers)
    assert resp.status_code == 403

    resp = client.post(f"/api/penalties/{penalty_id}/reverse", json={"reason": "mistake"}, headers=ceo_headers)
    assert resp.status_code == 200

    with app.app_context():
        loan = Loan.query.get(loan_id)
        assert loan.outstanding_balance == Decimal("100000.00")
        penalty = Penalty.query.get(penalty_id)
        assert penalty.status == "reversed"
        assert penalty.reversal_reason == "mistake"
        assert penalty.reversed_by == ceo.id


# ---------------------------------------------------------------- opening capital versioning


def test_opening_capital_versioning_stores_history(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    checker, checker_pw = make_user("checker")
    headers = auth_headers(ceo.email, ceo_pw)

    resp = client.post("/api/capital/opening", json={"new_value": 1000000, "reason": "initial seed capital"}, headers=headers)
    assert resp.status_code == 201
    first = resp.get_json()["capital_entry"]
    assert first["previous_value"] == 0
    assert first["new_value"] == 1000000

    resp = client.post("/api/capital/opening", json={"new_value": 1500000, "reason": "additional injection"}, headers=headers)
    assert resp.status_code == 201
    second = resp.get_json()["capital_entry"]
    assert second["previous_value"] == 1000000
    assert second["new_value"] == 1500000

    resp = client.get("/api/capital/opening", headers=headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["capital_entries"]) == 2

    resp = client.get("/api/capital/summary", headers=headers)
    body = resp.get_json()
    assert body["opening_capital"] == 1500000
    assert body["cash_on_hand"] == 1500000  # nothing else moved cash in this test

    resp = client.post("/api/capital/opening", json={"new_value": 1, "reason": "x"}, headers=auth_headers(checker.email, checker_pw))
    assert resp.status_code == 403


# ---------------------------------------------------------------- job_title vs permission role


def test_job_title_never_alters_permission_role(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    headers = auth_headers(ceo.email, ceo_pw)

    resp = client.post(
        "/api/auth/register",
        json={
            "name": "Test Maker", "email": "jobtitle@example.com", "phone": "0700999888",
            "role": "maker", "department": "loans_credit", "job_title": "Branch Manager", "salary": 500000,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["role"] == "maker"
    assert body["employee"]["job_title"] == "Branch Manager"


def test_register_with_employee_option_none_skips_employee(client, make_user, auth_headers):
    """employee_option is a radio choice, not a checkbox default (Part 2.1):
    "create" (default), "link" (existing employee, no login yet), "none"."""
    ceo, ceo_pw = make_user("ceo")
    headers = auth_headers(ceo.email, ceo_pw)

    resp = client.post(
        "/api/auth/register",
        json={
            "name": "No Employee", "email": "noemployee@example.com", "phone": "0700999887",
            "role": "checker", "department": "loans_credit", "employee_option": "none",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert "employee" not in resp.get_json()


def test_register_with_employee_option_link_attaches_the_existing_employee(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    headers = auth_headers(ceo.email, ceo_pw)
    loose = client.post("/api/employees", json={"name": "Loose Hand", "phone": "0700555444", "job_title": "Teller", "salary": 400000, "start_date": "2026-01-01"}, headers=headers).get_json()["employee"]

    resp = client.post(
        "/api/auth/register",
        json={
            "name": "Linked", "email": "linked-on-create@example.com", "phone": "0700999886",
            "role": "maker", "department": "loans_credit", "employee_option": "link", "employee_id": loose["id"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["employee"]["id"] == loose["id"]
    # linking the same employee again is refused — it already has a login
    again = client.post(
        "/api/auth/register",
        json={"name": "X", "email": "x2@example.com", "phone": "0700999885", "role": "maker", "employee_option": "link", "employee_id": loose["id"]},
        headers=headers,
    )
    assert again.status_code == 409
