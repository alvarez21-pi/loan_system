"""Integration-level role access matrix: logs in as each of the seven real
account shapes (CEO, Head Manager, HR/Finance/Loans Department Manager,
Checker, Maker) and calls the actual HTTP endpoints for every module named
in the PRD's role table (§2) — borrowers, loans, repayments, settlement,
penalties, expenses, payroll, leave, reports, users, backups —
asserting the allowed/forbidden result each role should get.

This is deliberately a different layer from test_permission_matrix_and_
setup.py, which already covers has_permission() itself exhaustively at the
unit level (plain Python objects, no HTTP, no Flask). This file instead
proves each ROUTE is wired to the right permission string and that the
resulting HTTP status actually matches the PRD, which a unit test on
has_permission() alone cannot catch (e.g. a route that forgot its
@permission_required decorator, or used the wrong permission string).

Every expectation below is cited to a specific rule:
- PRD.md §2 (roles) for who holds which fixed/scoped permission.
- services/permissions.py (PERMISSION_MODULE, CHECKER_PERMISSIONS,
  MAKER_PERMISSIONS, GLOBAL_ONLY_PERMISSIONS) for the exact permission
  string each route checks.
- The route file itself for which permission string a given endpoint
  actually enforces (some routes use a bespoke check — e.g. users.py's
  assignable_roles_for — rather than has_permission() directly; the
  expectations here follow the ROUTE's real behavior, not a guess).
"""
from datetime import date

import pytest

from extensions import db
from models import Employee


@pytest.fixture()
def roster(app, make_user, auth_headers):
    """One of every real account shape — department set per PRD §2's
    department -> module table, not an arbitrary choice. Each also gets a
    linked Employee record (own-leave-request tests need one to identify
    "acting for self" — see routes/operations.py's create_leave)."""
    people = {
        "ceo": make_user("ceo"),
        "head_manager": make_user("head_manager"),
        "hr_manager": make_user("department_manager", name="HR Manager", email="hr.manager@example.com", department="hr"),
        "finance_manager": make_user("department_manager", name="Finance Manager", email="finance.manager@example.com", department="finance"),
        "loans_manager": make_user("department_manager", name="Loans Manager", email="loans.manager@example.com", department="loans_credit"),
        "checker": make_user("checker", department="loans_credit"),
        "maker": make_user("maker", department="loans_credit"),
    }
    users = {key: pair[0] for key, pair in people.items()}
    headers = {key: auth_headers(pair[0].email, pair[1]) for key, pair in people.items()}
    employee_ids = {}
    with app.app_context():
        for key, user in users.items():
            employee = Employee(
                name=user.name, job_title="Staff", salary=100000, phone=user.phone,
                email=user.email, start_date=date(2026, 1, 1), is_active=True, user_id=user.id,
            )
            db.session.add(employee)
            db.session.flush()
            employee_ids[key] = employee.id
        db.session.commit()
    return users, headers, employee_ids


ALL_ROLES = ("ceo", "head_manager", "hr_manager", "finance_manager", "loans_manager", "checker", "maker")


def assert_role_results(client, method, path, headers_by_role, allowed_roles, json=None, success_codes=(200, 201)):
    """Calls `path` as every role in ALL_ROLES and asserts each got the
    right side of the allow/forbid line — one assertion per role, with the
    role name in the failure output so a mismatch is immediately readable."""
    for role in ALL_ROLES:
        response = client.open(path, method=method, json=json, headers=headers_by_role[role])
        if role in allowed_roles:
            assert response.status_code in success_codes, (
                f"{role} should be ALLOWED to {method} {path} (PRD §2) but got "
                f"{response.status_code}: {response.get_json()}"
            )
        else:
            assert response.status_code == 403, (
                f"{role} should be FORBIDDEN from {method} {path} (PRD §2) but got "
                f"{response.status_code}: {response.get_json()}"
            )


# ------------------------------------------------------------------------- borrowers

def test_create_borrower_allowed_for_everyone_whose_module_reach_includes_it(client, roster):
    """borrowers:manage -> "borrowers" module (loans_credit/general) +
    checker/maker's fixed set (PRD §2 points 4/5)."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager", "checker", "maker"}
    for i, role in enumerate(ALL_ROLES):
        response = client.post("/api/borrowers", json={
            "name": f"Borrower {role}", "phone": f"0711{i:06d}", "id_number": f"BW-{role}-{i}",
        }, headers=headers[role])
        if role in allowed:
            assert response.status_code == 201, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- loans

@pytest.fixture()
def a_borrower(client, roster):
    _, headers, _ = roster
    response = client.post("/api/borrowers", json={
        "name": "Loan Test Borrower", "phone": "0722000001", "id_number": "LOANTEST-1",
    }, headers=headers["maker"])
    assert response.status_code == 201, response.get_json()
    return response.get_json()["borrower"]["id"]


def test_create_loan_forbidden_for_checker_hard_rule_and_non_loans_departments(client, roster, a_borrower):
    """loans:create -> "loans" module (loans_credit/general) + maker's fixed
    set. A checker can NEVER create a loan — the one hard rule PRD §2 point
    4 states with no exception, even though a checker otherwise holds a
    broad fixed set."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager", "maker"}
    for i, role in enumerate(ALL_ROLES):
        response = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 100000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers[role])
        if role in allowed:
            assert response.status_code == 201, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())
            assert role != "checker" or "permission" in response.get_json().get("message", "").lower()


def test_approve_loan_forbidden_for_maker_hard_rule_allowed_for_checker(client, roster, a_borrower):
    """loans:approve -> checker holds this (approve ANY loan, PRD §2 point
    4); maker NEVER approves anything (point 5's hard rule), even though a
    maker otherwise creates loans. Approved by someone who did NOT create
    it, so self-approval exemption never confounds this result."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager", "checker"}
    for role in allowed | {"maker"}:
        created = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 50000, "interest_rate": 5,
            "term_months": 3, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id = created.get_json()["loan"]["id"]
        response = client.post(f"/api/loans/{loan_id}/approve", headers=headers[role])
        if role == "maker":
            assert response.status_code == 403, response.get_json()
        else:
            assert response.status_code == 200, (role, response.get_json())


def test_hr_and_finance_managers_cannot_touch_loans_at_all(client, roster, a_borrower):
    _, headers, _ = roster
    created = client.post("/api/loans", json={
        "borrower_id": a_borrower, "principal_amount": 50000, "interest_rate": 5,
        "term_months": 3, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    loan_id = created.get_json()["loan"]["id"]
    for role in ("hr_manager", "finance_manager"):
        assert client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 1, "interest_rate": 1, "term_months": 1, "start_date": "2026-01-01",
        }, headers=headers[role]).status_code == 403
        assert client.post(f"/api/loans/{loan_id}/approve", headers=headers[role]).status_code == 403


# ------------------------------------------------------------------------- repayments + settlement

def test_record_repayment_allowed_for_loans_department_and_both_fixed_tiers(client, roster, a_borrower):
    """repayments:record -> "repayments" module (loans_credit/general) +
    both checker's and maker's fixed set."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager", "checker", "maker"}
    for i, role in enumerate(ALL_ROLES):
        created = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 100000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id = created.get_json()["loan"]["id"]
        client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
        response = client.post("/api/repayments", json={
            "loan_id": loan_id, "amount_paid": 1000, "payment_date": "2026-02-01",
            "idempotency_key": f"repay-{role}-{i}",
        }, headers=headers[role])
        if role in allowed:
            assert response.status_code == 201, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


def test_settlement_discount_forbidden_for_checker_and_maker_specifically(client, roster, a_borrower):
    """settlement:discount is deliberately NOT in either CHECKER_PERMISSIONS
    or MAKER_PERMISSIONS (services/permissions.py's own comment) even though
    both hold repayments:record and can settle a loan WITHOUT a discount.
    Loans Manager/Head Manager/CEO may apply one; HR/Finance Manager can't
    even reach settle() at all (no repayments:record)."""
    _, headers, _ = roster
    discount_allowed = {"ceo", "head_manager", "loans_manager"}
    settle_allowed = discount_allowed | {"checker", "maker"}
    for role in ALL_ROLES:
        created = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 200000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id = created.get_json()["loan"]["id"]
        client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])

        # Settling WITHOUT a discount: gated only by repayments:record.
        no_discount = client.post(f"/api/loans/{loan_id}/settle", json={
            "idempotency_key": f"settle-plain-{role}",
        }, headers=headers[role])
        if role in settle_allowed:
            assert no_discount.status_code == 201, (role, no_discount.get_json())
        else:
            assert no_discount.status_code == 403, (role, no_discount.get_json())

        # A SEPARATE loan, settling WITH a discount: gated by settlement:discount.
        created2 = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 200000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id2 = created2.get_json()["loan"]["id"]
        client.post(f"/api/loans/{loan_id2}/approve", headers=headers["checker"])
        with_discount = client.post(f"/api/loans/{loan_id2}/settle", json={
            "discount": 10, "discount_reason": "goodwill", "idempotency_key": f"settle-disc-{role}",
        }, headers=headers[role])
        if role in discount_allowed:
            assert with_discount.status_code == 201, (role, with_discount.get_json())
        elif role in settle_allowed:
            # Checker/maker: settle itself is allowed, but the discount
            # specifically is refused — a 403, not a silent ignore.
            assert with_discount.status_code == 403, (role, with_discount.get_json())
        else:
            assert with_discount.status_code == 403, (role, with_discount.get_json())


# ------------------------------------------------------------------------- penalties

def test_create_penalty_allowed_for_loans_department_and_both_fixed_tiers(client, roster, a_borrower):
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager", "checker", "maker"}
    for role in ALL_ROLES:
        created = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 100000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id = created.get_json()["loan"]["id"]
        client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
        response = client.post("/api/penalties", json={
            "loan_id": loan_id, "amount": 500, "reason": "late fee",
        }, headers=headers[role])
        if role in allowed:
            assert response.status_code == 201, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


def test_approve_penalty_is_department_manager_and_above_only_never_checker_or_maker(client, roster, a_borrower):
    """penalties:approve is in neither CHECKER_PERMISSIONS nor
    MAKER_PERMISSIONS at all — unlike loans:approve, a checker does NOT
    hold this (PRD §2 point 4: "A Checker never approves a penalty
    either")."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "loans_manager"}
    for role in ALL_ROLES:
        created = client.post("/api/loans", json={
            "borrower_id": a_borrower, "principal_amount": 100000, "interest_rate": 10,
            "term_months": 6, "start_date": "2026-01-01",
        }, headers=headers["maker"])
        loan_id = created.get_json()["loan"]["id"]
        client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
        penalty = client.post("/api/penalties", json={
            "loan_id": loan_id, "amount": 500, "reason": "late fee",
        }, headers=headers["maker"])
        penalty_id = penalty.get_json()["penalty"]["id"]
        response = client.post(f"/api/penalties/{penalty_id}/approve", headers=headers[role])
        if role in allowed:
            assert response.status_code == 200, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- expenses

def test_expenses_allowed_for_finance_department_and_both_fixed_tiers_not_loans(client, roster):
    """expenses:manage -> "expenses" module (finance/general) PLUS both
    checker's and maker's fixed set — notably NOT the Loans Manager, since
    expenses isn't in the loans_credit module list."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "finance_manager", "checker", "maker"}
    for role in ALL_ROLES:
        response = client.post("/api/expenses", json={
            "description": "Office supplies", "category": "office", "amount": 1000, "date": "2026-01-15",
        }, headers=headers[role])
        if role in allowed:
            assert response.status_code == 201, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- payroll

def test_payroll_is_hr_department_and_above_only(client, roster):
    """payroll:manage -> "payroll" module (hr/general only) — not in
    CHECKER_PERMISSIONS or MAKER_PERMISSIONS, and not the Finance or Loans
    Manager's module list."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "hr_manager"}
    for role in ALL_ROLES:
        response = client.get("/api/payroll", headers=headers[role])
        if role in allowed:
            assert response.status_code == 200, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- leave

def test_everyone_may_request_their_own_leave_regardless_of_role(client, roster):
    """PRD §2: "filing your OWN leave request is open to every tier
    regardless of department" — the one deliberate exception to the
    module-gated pattern everything else here follows."""
    _, headers, employee_ids = roster
    for role in ALL_ROLES:
        response = client.post("/api/leave-requests", json={
            "employee_id": employee_ids[role], "leave_type": "annual",
            "start_date": "2026-03-01", "end_date": "2026-03-02", "reason": "test",
        }, headers=headers[role])
        assert response.status_code == 201, (role, response.get_json())


def test_leave_approval_is_hr_department_and_above_only(client, roster):
    """leave:manage -> "leave_requests" module (hr/general only) — a
    Checker/Maker stays request-only for their OWN leave and never holds
    this, matching PRD §2's "never a Checker or a Maker" for approval."""
    _, headers, employee_ids = roster
    allowed = {"ceo", "head_manager", "hr_manager"}
    for role in ALL_ROLES:
        leave = client.post("/api/leave-requests", json={
            "employee_id": employee_ids["maker"], "leave_type": "annual",
            "start_date": "2026-04-01", "end_date": "2026-04-02", "reason": "test",
        }, headers=headers["maker"])
        leave_id = leave.get_json()["leave_request"]["id"]
        response = client.post(f"/api/leave-requests/{leave_id}/approve", headers=headers[role])
        if role in allowed:
            assert response.status_code == 200, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- reports

def test_reports_is_finance_department_and_above_only(client, roster):
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "finance_manager"}
    for role in ALL_ROLES:
        response = client.get("/api/reports/portfolio-at-risk", headers=headers[role])
        if role in allowed:
            assert response.status_code == 200, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- users

def test_users_list_reaches_every_manager_tier_scoped_never_checker_or_maker(client, roster):
    """GET /api/users is gated by users.py's own user_manager decorator
    (assignable_roles_for), NOT a generic users:manage has_permission()
    check (that permission string is never actually consulted by this
    route) — so every department_manager reaches it too, scoped to their
    own department server-side, not just ceo/head_manager."""
    _, headers, _ = roster
    allowed = {"ceo", "head_manager", "hr_manager", "finance_manager", "loans_manager"}
    for role in ALL_ROLES:
        response = client.get("/api/users", headers=headers[role])
        if role in allowed:
            assert response.status_code == 200, (role, response.get_json())
        else:
            assert response.status_code == 403, (role, response.get_json())


# ------------------------------------------------------------------------- audit / backup (ceo + head_manager only)

@pytest.mark.parametrize("method,path,json", [
    ("GET", "/api/audit-logs", None),
    ("GET", "/api/backup/status", None),
])
def test_global_only_capabilities_are_ceo_and_head_manager_only(client, roster, method, path, json):
    """audit:view/backup:manage are GLOBAL_ONLY_PERMISSIONS — unconditionally
    false for every role except ceo/head_manager (services/permissions.py),
    including a department_manager who would otherwise look "senior"."""
    _, headers, _ = roster
    assert_role_results(client, method, path, headers, allowed_roles={"ceo", "head_manager"}, json=json)


def test_there_is_no_settings_page_or_api_for_anyone(client, roster):
    """The Settings page/table/API is removed entirely — every former
    setting is now a fixed value in backend/branding.py, not editable or
    even readable through the API, by any role."""
    _, headers, _ = roster
    for role in ALL_ROLES:
        assert client.get("/api/settings/company", headers=headers[role]).status_code == 404, role
        assert client.put("/api/settings/company", json={}, headers=headers[role]).status_code == 404, role


# ------------------------------------------------------------------------- CEO is untouchable

def test_ceo_account_cannot_be_deactivated_or_deleted_by_anyone_including_another_ceo(client, roster, make_user, auth_headers):
    """PRD §2 point 1: "untouchable by anyone else, including another CEO
    if one ever exists" — guard_ceo() in routes/users.py applies
    unconditionally, with no self-exception."""
    users, headers, _ = roster
    ceo = users["ceo"]
    for actor_role in ("head_manager", "ceo"):
        response = client.patch(f"/api/users/{ceo.id}", json={"is_active": False}, headers=headers[actor_role])
        assert response.status_code == 403, (actor_role, response.get_json())
        response = client.delete(f"/api/users/{ceo.id}", headers=headers[actor_role])
        assert response.status_code == 403, (actor_role, response.get_json())


def test_ceo_can_approve_a_loan_they_created_themselves(client, roster):
    """PRD §2's self-approval exemption explicitly includes the CEO —
    created_by == approved_by is allowed for ceo/head_manager/
    department_manager, unlike a checker/maker (no exception for those two)."""
    _, headers, _ = roster
    borrower = client.post("/api/borrowers", json={
        "name": "CEO Self-Approval Test", "phone": "0733000001", "id_number": "SELFAPPROVE-1",
    }, headers=headers["ceo"])
    # CEO doesn't hold loans:create directly in the fixed-tier sense, but
    # is unscoped (has every permission) — create AS the ceo, then approve
    # AS the same ceo.
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"], "principal_amount": 100000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers["ceo"])
    loan_id = loan.get_json()["loan"]["id"]
    response = client.post(f"/api/loans/{loan_id}/approve", headers=headers["ceo"])
    assert response.status_code == 200, response.get_json()


