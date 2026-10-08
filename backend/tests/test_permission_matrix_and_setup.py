"""Part 10 coverage: the tier + department model itself (unit level), opening
capital settable once, borrower duplicate-ID blocking, checkers unable to
create loans, token expiry with a tiny TTL, and the full set-password flow."""
import time
from datetime import date

from services.permissions import (
    DEPARTMENT_MODULES,
    can_create_tier,
    has_permission,
    role_label,
)


# ---------------------------------------------------------------- unit: tiers


def test_ceo_and_head_manager_have_every_permission_unconditionally():
    class U:
        def __init__(self, role, department=None):
            self.role = role
            self.department = department

    for permission in ("loans:approve", "employees:manage", "capital:manage", "users:manage"):
        assert has_permission(U("ceo"), permission) is True
        assert has_permission(U("head_manager"), permission) is True


def test_department_manager_gets_full_access_within_their_department_only():
    class U:
        def __init__(self, role, department=None):
            self.role = role
            self.department = department

    finance_manager = U("department_manager", "finance")
    assert has_permission(finance_manager, "capital:manage") is True
    assert has_permission(finance_manager, "expenses:manage") is True
    assert has_permission(finance_manager, "loans:approve") is False  # loans isn't a finance module
    assert has_permission(finance_manager, "loans:create") is False

    loans_manager = U("department_manager", "loans_credit")
    assert has_permission(loans_manager, "loans:create") is True
    assert has_permission(loans_manager, "loans:approve") is True  # full access — both, unlike checker/maker
    assert has_permission(loans_manager, "penalties:approve") is True
    assert has_permission(loans_manager, "capital:view") is False  # capital isn't a loans_credit module


def test_checker_and_maker_hold_a_fixed_action_set_with_no_department_restriction():
    """Part 4 simplification: department plays no part at all in what a
    checker/maker can do — the SAME fixed action set applies regardless of
    which department (if any) is on their account."""
    class U:
        def __init__(self, role, department=None):
            self.role = role
            self.department = department

    for department in ("loans_credit", "hr", "finance", "general", None):
        checker = U("checker", department)
        maker = U("maker", department)
        # Hard rules, no exception: a checker never creates a loan or approves
        # leave/a penalty; a maker never approves anything.
        assert has_permission(checker, "loans:create") is False
        assert has_permission(checker, "leave:manage") is False
        assert has_permission(checker, "penalties:approve") is False
        assert has_permission(maker, "loans:approve") is False
        # Both create borrowers/repayments/expenses/penalties/own-leave, and
        # a checker additionally approves ANY loan — identically in every department.
        for permission in ("borrowers:manage", "repayments:record", "expenses:manage", "penalties:create", "leave:request"):
            assert has_permission(checker, permission) is True, (department, permission)
            assert has_permission(maker, permission) is True, (department, permission)
        assert has_permission(checker, "loans:approve") is True
        assert has_permission(maker, "loans:create") is True
        # Neither ever reaches reports, assets, employees, payroll, capital,
        # or any admin-only capability — regardless of department.
        for permission in ("reports:view", "assets:manage", "employees:manage", "payroll:manage", "capital:view", "users:manage", "audit:view", "backup:manage"):
            assert has_permission(checker, permission) is False
            assert has_permission(maker, permission) is False


def test_department_manager_still_gated_by_department_unlike_checker_maker():
    """Only department_manager (and above) still has department-gated
    access — the simplification in Part 4 is specific to checker/maker."""
    class U:
        def __init__(self, role, department=None):
            self.role = role
            self.department = department

    hr_manager = U("department_manager", "hr")
    assert has_permission(hr_manager, "loans:approve") is False
    assert has_permission(hr_manager, "borrowers:manage") is False
    assert has_permission(hr_manager, "leave:manage") is True  # leave IS an hr module
    assert has_permission(hr_manager, "employees:manage") is True


def test_department_module_mapping_matches_the_spec():
    assert DEPARTMENT_MODULES["hr"] == {"employees", "payroll", "leave_requests"}
    assert DEPARTMENT_MODULES["finance"] == {"expenses", "capital", "assets", "reports"}
    assert DEPARTMENT_MODULES["loans_credit"] == {"borrowers", "loans", "repayments", "penalties", "calculator"}
    # General is the catch-all: every module any other department reaches.
    assert DEPARTMENT_MODULES["general"] == (
        DEPARTMENT_MODULES["hr"] | DEPARTMENT_MODULES["finance"] | DEPARTMENT_MODULES["loans_credit"]
    )


def test_role_label_shows_the_derived_department_manager_title():
    assert role_label("department_manager", "hr") == "HR Manager"
    assert role_label("department_manager", "finance") == "Finance Manager"
    assert role_label("department_manager", "loans_credit") == "Loans Manager"
    assert role_label("ceo") == "CEO"
    assert role_label("head_manager") == "Head Manager"


def test_creation_hierarchy():
    class A:
        def __init__(self, role, department=None):
            self.role = role
            self.department = department

    ceo, head_manager = A("ceo"), A("head_manager")
    dept_manager = A("department_manager", "hr")
    checker, maker = A("checker", "hr"), A("maker", "hr")

    assert can_create_tier(ceo, "head_manager") is True
    assert can_create_tier(head_manager, "head_manager") is False  # can't create a peer
    assert can_create_tier(head_manager, "department_manager", "finance") is True
    assert can_create_tier(dept_manager, "checker", "hr") is True
    assert can_create_tier(dept_manager, "checker", "finance") is False  # wrong department
    assert can_create_tier(dept_manager, "department_manager", "hr") is False  # can't create a manager
    assert can_create_tier(checker, "maker", "hr") is False
    assert can_create_tier(maker, "maker", "hr") is False


# ------------------------------------------------------------- API: matrix


def test_checker_cannot_create_a_loan_api_level(client, make_user, auth_headers):
    checker, pw = make_user("checker")
    # need a ceo to make the product/borrower since checker lacks borrowers:manage
    ceo, ceo_pw = make_user("ceo", email="ceo-b@example.com")
    ceo_headers = auth_headers(ceo.email, ceo_pw)
    borrower = client.post("/api/borrowers", json={"name": "B2", "phone": "0700", "id_number": "ID-CHK-LOAN-2"}, headers=ceo_headers).get_json()["borrower"]
    product = client.post("/api/loan-products", json={"name": "ForChecker", "default_interest_rate": 10}, headers=ceo_headers).get_json()["loan_product"]

    denied = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=auth_headers(checker.email, pw))
    assert denied.status_code == 403


# ------------------------------------------------------------- capital: opening once


def test_opening_capital_is_a_one_time_setup_then_ceo_only_with_reason(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    head_manager, head_manager_pw = make_user("head_manager")
    ceo_headers = auth_headers(ceo.email, ceo_pw)
    head_manager_headers = auth_headers(head_manager.email, head_manager_pw)

    # first-time setup: no reason required, a head manager may do it
    first = client.post("/api/capital/opening", json={"new_value": 2_000_000}, headers=head_manager_headers)
    assert first.status_code == 201, first.get_json()
    assert first.get_json()["capital_entry"]["reason"] is None

    # once set, a correction needs a reason...
    no_reason = client.post("/api/capital/opening", json={"new_value": 2_500_000}, headers=ceo_headers)
    assert no_reason.status_code == 400

    # ...and only the CEO may make it, even though a head manager set the original
    head_manager_tries = client.post("/api/capital/opening", json={"new_value": 2_500_000, "reason": "correction"}, headers=head_manager_headers)
    assert head_manager_tries.status_code == 403

    corrected = client.post("/api/capital/opening", json={"new_value": 2_500_000, "reason": "correction"}, headers=ceo_headers)
    assert corrected.status_code == 201
    assert corrected.get_json()["capital_entry"]["previous_value"] == 2_000_000

    history = client.get("/api/capital/opening", headers=ceo_headers).get_json()["capital_entries"]
    assert len(history) == 2  # the previous value is kept in history, never overwritten


# ------------------------------------------------------------- borrowers: duplicate ID


def test_duplicate_borrower_id_is_blocked_with_a_link_to_the_existing_one(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    headers = auth_headers(ceo.email, ceo_pw)

    first = client.post("/api/borrowers", json={"name": "Original", "phone": "0700111222", "id_number": "19900101111110001", "id_type": "nida"}, headers=headers)
    assert first.status_code == 201
    original_id = first.get_json()["borrower"]["id"]

    duplicate = client.post("/api/borrowers", json={"name": "Impersonator", "phone": "0700333444", "id_number": "19900101111110001", "id_type": "nida"}, headers=headers)
    assert duplicate.status_code == 409
    body = duplicate.get_json()
    assert body["existing_borrower_id"] == original_id
    assert body["existing_borrower_name"] == "Original"

    # a different id_type with the same digits is not a collision
    different_type = client.post("/api/borrowers", json={"name": "Someone Else", "phone": "0700555666", "id_number": "19900101111110001", "id_type": "passport"}, headers=headers)
    assert different_type.status_code == 201

    # a non-20-digit NIDA number is a soft warning, never a block
    short = client.post("/api/borrowers", json={"name": "Short NIDA", "phone": "0700777888", "id_number": "12345", "id_type": "nida"}, headers=headers)
    assert short.status_code == 201
    assert "warning" in short.get_json()


# ------------------------------------------------------------- token expiry


def test_account_setup_link_expires_on_a_tiny_ttl(client, make_user, app):
    from services.accounts import reset_token

    ceo, _ = make_user("ceo")
    with app.app_context():
        from models import User
        target = User.query.get(ceo.id)
        token = reset_token(target, "account_setup")

    app.config["VERIFICATION_TOKEN_TTL_HOURS"] = 1 / 3600000  # ~1 millisecond: any real delay expires it
    time.sleep(1.1)
    expired = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "NewPassw0rd!9"})
    assert expired.status_code == 400
    assert expired.get_json().get("expired") is True


def test_password_reset_link_expires_on_a_tiny_ttl(client, make_user, app):
    from services.accounts import reset_token

    user, _ = make_user("maker", email="expiry-target@example.com")
    with app.app_context():
        from models import User
        target = User.query.get(user.id)
        token = reset_token(target, "password_reset")

    app.config["PASSWORD_RESET_TTL_MINUTES"] = 1 / 60000  # ~1 millisecond: any real delay expires it
    time.sleep(1.1)
    expired = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "NewPassw0rd!9"})
    assert expired.status_code == 400
    assert expired.get_json().get("expired") is True


def test_resend_verification_is_generic_and_actually_resends(client, make_user, auth_headers, monkeypatch):
    ceo, ceo_pw = make_user("ceo")
    unverified, _ = make_user("maker", email="not-verified@example.com", verified=False)

    sent = []
    monkeypatch.setattr("services.accounts.send_email_async", lambda *a, **kw: sent.append((a, kw)))

    # generic response whether or not the email exists — never confirms an account
    unknown = client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"})
    known = client.post("/api/auth/resend-verification", json={"email": unverified.email})
    assert unknown.status_code == known.status_code == 202
    assert unknown.get_json() == known.get_json()
    assert len(sent) == 1  # only the real, unverified account actually got queued

    # a ceo/head manager/department manager can also trigger it from the Users page
    from_users_page = client.post(f"/api/users/{unverified.id}/resend-verification", headers=auth_headers(ceo.email, ceo_pw))
    assert from_users_page.status_code == 200
    assert len(sent) == 2


# ------------------------------------------------------------- full set-password flow


def test_full_set_password_flow_create_link_set_login(client, make_user, auth_headers, app, monkeypatch):
    """create user -> email link -> set password -> log in, end to end
    (Part 8.4), using the real token/endpoint path the email link points at."""
    ceo, ceo_pw = make_user("ceo")

    captured = {}
    monkeypatch.setattr("services.accounts.send_email_async", lambda kind, to, data: captured.update(data))

    created = client.post("/api/auth/register", json={
        "name": "New Hire", "email": "new-hire@example.com", "phone": "0700123123", "role": "maker", "department": "loans_credit",
    }, headers=auth_headers(ceo.email, ceo_pw))
    assert created.status_code == 201
    assert "verify_link" in captured
    token = captured["verify_link"].split("setup=")[-1]

    # cannot log in yet — unverified
    blocked = client.post("/api/auth/login", json={"email": "new-hire@example.com", "password": "BrandNewPassw0rd!9"})
    assert blocked.status_code == 401 or blocked.status_code == 403

    set_password = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "BrandNewPassw0rd!9"})
    assert set_password.status_code == 200

    logged_in = client.post("/api/auth/login", json={"email": "new-hire@example.com", "password": "BrandNewPassw0rd!9"})
    assert logged_in.status_code == 200
    assert logged_in.get_json()["user"]["email"] == "new-hire@example.com"
    assert logged_in.get_json()["user"]["email_verified"] is True
