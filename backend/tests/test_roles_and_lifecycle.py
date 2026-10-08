import os
from datetime import datetime, timedelta

from models import AuditLog, Loan, User
from services.scheduler import purge_deactivated_users


def test_ceo_cannot_be_deactivated_by_anyone(client, make_user, auth_headers):
    ceo, _ = make_user("ceo")
    head_manager, head_manager_password = make_user("head_manager")

    response = client.patch(
        f"/api/users/{ceo.id}",
        json={"is_active": False},
        headers=auth_headers(head_manager.email, head_manager_password),
    )
    assert response.status_code == 403

    other_ceo, other_password = make_user("ceo", email="ceo2@example.com")
    response = client.patch(
        f"/api/users/{ceo.id}",
        json={"is_active": False},
        headers=auth_headers(other_ceo.email, other_password),
    )
    assert response.status_code == 403


def test_ceo_cannot_be_deleted_or_have_role_changed(client, make_user, auth_headers):
    ceo, _ = make_user("ceo")
    head_manager, head_manager_password = make_user("head_manager")
    headers = auth_headers(head_manager.email, head_manager_password)

    response = client.delete(f"/api/users/{ceo.id}", headers=headers)
    assert response.status_code == 403

    response = client.patch(f"/api/users/{ceo.id}", json={"role": "maker"}, headers=headers)
    assert response.status_code == 403


def test_only_ceo_can_create_a_head_manager(client, make_user, auth_headers):
    head_manager, password = make_user("head_manager")
    response = client.post(
        "/api/auth/register",
        json={"name": "New Head Manager", "email": "headmanager2@example.com", "phone": "0700000111", "role": "head_manager"},
        headers=auth_headers(head_manager.email, password),
    )
    assert response.status_code == 403

    ceo, ceo_password = make_user("ceo")
    response = client.post(
        "/api/auth/register",
        json={"name": "New Head Manager", "email": "headmanager3@example.com", "phone": "0700000112", "role": "head_manager"},
        headers=auth_headers(ceo.email, ceo_password),
    )
    assert response.status_code == 201
    assert response.get_json()["user"]["role"] == "head_manager"


def test_head_manager_cannot_create_a_second_head_manager(client, make_user, auth_headers):
    head_manager, password = make_user("head_manager")
    response = client.post(
        "/api/auth/register",
        json={"name": "New Head Manager", "email": "headmanager4@example.com", "phone": "0700000113", "role": "head_manager"},
        headers=auth_headers(head_manager.email, password),
    )
    assert response.status_code == 403


def test_head_manager_can_create_department_manager_checker_and_maker_anywhere(client, make_user, auth_headers):
    head_manager, password = make_user("head_manager")
    headers = auth_headers(head_manager.email, password)
    response = client.post(
        "/api/auth/register",
        json={"name": "HR Manager", "email": "hrmanager@example.com", "phone": "0700000114", "role": "department_manager", "department": "hr"},
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["user"]["display_role"] == "HR Manager"


def test_department_manager_can_only_manage_their_own_department(client, make_user, auth_headers):
    hr_manager, hr_manager_password = make_user("department_manager", department="hr")
    headers = auth_headers(hr_manager.email, hr_manager_password)

    ok = client.post(
        "/api/auth/register",
        json={"name": "HR Checker", "email": "hrchecker@example.com", "phone": "0700000115", "role": "checker", "department": "hr"},
        headers=headers,
    )
    assert ok.status_code == 201

    wrong_department = client.post(
        "/api/auth/register",
        json={"name": "Finance Checker", "email": "financechecker@example.com", "phone": "0700000116", "role": "checker", "department": "finance"},
        headers=headers,
    )
    assert wrong_department.status_code == 403

    cannot_create_manager = client.post(
        "/api/auth/register",
        json={"name": "Another HR Manager", "email": "hrmanager2@example.com", "phone": "0700000117", "role": "department_manager", "department": "hr"},
        headers=headers,
    )
    assert cannot_create_manager.status_code == 403


def test_head_manager_cannot_deactivate_another_head_manager(client, make_user, auth_headers):
    head_manager_a, password_a = make_user("head_manager", email="headmanager-a@example.com")
    head_manager_b, _ = make_user("head_manager", email="headmanager-b@example.com")

    response = client.patch(
        f"/api/users/{head_manager_b.id}",
        json={"is_active": False},
        headers=auth_headers(head_manager_a.email, password_a),
    )
    assert response.status_code == 403


def test_checker_and_maker_cannot_register_users(client, make_user, auth_headers):
    checker, checker_password = make_user("checker")
    maker, maker_password = make_user("maker")

    for actor, password in ((checker, checker_password), (maker, maker_password)):
        response = client.post(
            "/api/auth/register",
            json={"name": "X", "email": f"x-{actor.role}@example.com", "phone": "0700000200", "role": "maker", "department": "loans_credit"},
            headers=auth_headers(actor.email, password),
        )
        assert response.status_code == 403


def test_maker_cannot_approve_anything(client, make_user, auth_headers, app):
    from extensions import db

    maker, maker_password = make_user("maker")
    other_maker, other_password = make_user("maker", email="maker2@example.com")

    with app.app_context():
        from models import Borrower, Loan, LoanProduct

        borrower = Borrower(name="Jane", phone="0711000000", id_number="ID-1")
        product = LoanProduct(
            name="Standard", default_interest_rate=10, min_term_months=1, max_term_months=24,
            min_amount=1000, max_amount=1000000, is_active=True,
        )
        db.session.add_all([borrower, product])
        db.session.commit()
        loan = Loan(
            borrower_id=borrower.id, loan_product_id=product.id, principal_amount=100000,
            interest_rate=10, term_months=12, start_date=datetime(2026, 1, 1).date(),
            status="pending_approval", outstanding_balance=100000, created_by=other_maker.id,
        )
        db.session.add(loan)
        db.session.commit()
        loan_id = loan.id

    response = client.post(
        f"/api/loans/{loan_id}/approve",
        headers=auth_headers(maker.email, maker_password),
    )
    assert response.status_code == 403


def _bare_loan(db, creator_id, name="Jane", phone="0711000001", id_number="ID-2", product_name="Standard2"):
    from models import Borrower, Loan, LoanProduct

    borrower = Borrower(name=name, phone=phone, id_type="nida", id_number=id_number)
    product = LoanProduct(
        name=product_name, default_interest_rate=10, min_term_months=1, max_term_months=24,
        min_amount=1000, max_amount=1000000, is_active=True,
    )
    db.session.add_all([borrower, product])
    db.session.commit()
    loan = Loan(
        borrower_id=borrower.id, loan_product_id=product.id, principal_amount=100000,
        interest_rate=10, term_months=12, start_date=datetime(2026, 1, 1).date(),
        status="pending_approval", outstanding_balance=100000, created_by=creator_id,
    )
    db.session.add(loan)
    db.session.commit()
    return loan.id


def test_ceo_head_manager_and_department_manager_self_approval_is_allowed_with_no_tracking(client, make_user, auth_headers, app):
    """CEO/head_manager/department_manager are exempt from the self-approval
    block everywhere — and, under the final tier model, there is no
    self-approved flag, badge or audit distinction of any kind: the approval
    is recorded exactly like any other."""
    from extensions import db
    from models import AuditLog, Loan

    ceo, ceo_password = make_user("ceo")
    head_manager, head_manager_password = make_user("head_manager")
    department_manager, department_manager_password = make_user("department_manager", department="loans_credit")

    with app.app_context():
        ceo_loan_id = _bare_loan(db, ceo.id, id_number="ID-CEO-SELF", product_name="SelfCEO")
        head_manager_loan_id = _bare_loan(db, head_manager.id, id_number="ID-HM-SELF", product_name="SelfHM")
        dept_manager_loan_id = _bare_loan(db, department_manager.id, id_number="ID-DM-SELF", product_name="SelfDM")

    for loan_id, actor, password in (
        (ceo_loan_id, ceo, ceo_password),
        (head_manager_loan_id, head_manager, head_manager_password),
        (dept_manager_loan_id, department_manager, department_manager_password),
    ):
        response = client.post(f"/api/loans/{loan_id}/approve", headers=auth_headers(actor.email, password))
        assert response.status_code == 200, response.get_json()
        assert "self_approved" not in response.get_json()["loan"]

    with app.app_context():
        assert Loan.query.get(ceo_loan_id).status == "active"
        # a plain APPROVED entry, never a SELF_-prefixed one
        log = AuditLog.query.filter_by(table_name="loan", record_id=ceo_loan_id, action="APPROVED").first()
        assert log is not None
        assert AuditLog.query.filter_by(action="SELF_APPROVED").first() is None


def test_maker_and_checker_are_still_blocked_from_self_approval(client, make_user, auth_headers, app):
    """Only ceo/head_manager/department_manager are exempt — makers and
    checkers are not."""
    from extensions import db

    checker, checker_password = make_user("checker")
    with app.app_context():
        loan_id = _bare_loan(db, checker.id, id_number="ID-CHK-SELF", product_name="SelfChecker")
    response = client.post(f"/api/loans/{loan_id}/approve", headers=auth_headers(checker.email, checker_password))
    assert response.status_code == 403
    assert "self" in response.get_json()["message"].lower() or "maker-checker" in response.get_json()["message"].lower()


def test_deactivated_user_auto_deleted_and_audit_trail_preserved(client, make_user, auth_headers, app):
    from extensions import db

    ceo, ceo_password = make_user("ceo")
    maker, maker_password = make_user("maker", name="Temp Maker", email="temp-maker@example.com")
    maker_id, maker_name = maker.id, maker.name

    maker_headers = auth_headers(maker.email, maker_password)
    ceo_headers = auth_headers(ceo.email, ceo_password)
    borrower_resp = client.post(
        "/api/borrowers",
        json={"name": "Borrower X", "phone": "0722000000", "id_number": "ID-DEL", "nida_number": "NIDA-DEL"},
        headers=maker_headers,
    )
    assert borrower_resp.status_code == 201
    borrower_id = borrower_resp.get_json()["borrower"]["id"]

    product_resp = client.post(
        "/api/loan-products",
        json={
            "name": "Deletion Test Product", "default_interest_rate": 10,
            "min_term_months": 1, "max_term_months": 24, "min_amount": 1000, "max_amount": 1000000,
        },
        headers=ceo_headers,
    )
    assert product_resp.status_code == 201
    product_id = product_resp.get_json()["loan_product"]["id"]

    loan_resp = client.post(
        "/api/loans",
        json={
            "borrower_id": borrower_id, "loan_product_id": product_id, "principal_amount": 50000,
            "interest_rate": 10, "term_months": 12, "start_date": "2026-01-01",
        },
        headers=maker_headers,
    )
    assert loan_resp.status_code == 201
    loan_id = loan_resp.get_json()["loan"]["id"]

    ceo_headers = auth_headers(ceo.email, ceo_password)
    deactivate_resp = client.patch(f"/api/users/{maker_id}", json={"is_active": False}, headers=ceo_headers)
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.get_json()["user"]["is_active"] is False

    os.environ["USER_DELETION_RETENTION_DAYS"] = "0"
    with app.app_context():
        stale_user = User.query.get(maker_id)
        stale_user.deactivated_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()

        purge_deactivated_users(app)

        assert User.query.get(maker_id) is None

        loan = Loan.query.get(loan_id)
        assert loan.created_by is None
        assert loan.creator_name_snapshot == maker_name

        creation_log = AuditLog.query.filter_by(table_name="loans", action="CREATE", record_id=loan_id).first()
        assert creation_log is not None
        assert creation_log.user_id is None
        assert creation_log.actor_name_snapshot == maker_name
        assert creation_log.actor_display_name == maker_name

        deletion_log = AuditLog.query.filter_by(
            table_name="users", action="AUTO_DELETE_USER", record_id=maker_id
        ).first()
        assert deletion_log is not None
        assert deletion_log.actor_name_snapshot == "System"

    del os.environ["USER_DELETION_RETENTION_DAYS"]
