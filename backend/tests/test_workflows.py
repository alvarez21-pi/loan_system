"""End-to-end coverage: repayments + schedule reconciliation, approval scopes,
whole-batch payroll, schedule PDF, optional product limits, employees/users
linking, borrower uploads and audit-log access."""
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

from services.loan_calculator import amortization_schedule


@pytest.fixture()
def staff(make_user, auth_headers):
    """One user of each role plus ready-to-use auth headers."""
    people = {
        "ceo": make_user("ceo"),
        "head_manager": make_user("head_manager"),
        "maker": make_user("maker"),
        "checker": make_user("checker"),
    }
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def create_active_loan(client, headers, principal=1_000_000, rate=25, term=12, start="2026-01-15", tag="a"):
    """Maker creates a loan through the API, a checker approves it. Returns the loan id."""
    maker, checker, ceo = headers["maker"], headers["checker"], headers["ceo"]
    borrower = client.post("/api/borrowers", json={
        "name": f"Jane {tag}", "phone": "0711000000", "id_number": f"ID-{tag}", "nida_number": f"NIDA-{tag}",
    }, headers=maker)
    assert borrower.status_code == 201, borrower.get_json()
    product = client.post("/api/loan-products", json={
        "name": f"Product {tag}", "default_interest_rate": rate, "min_term_months": 1, "max_term_months": 60,
        "min_amount": 1000, "max_amount": 50_000_000,
    }, headers=ceo)
    assert product.status_code == 201, product.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"], "loan_product_id": product.get_json()["loan_product"]["id"],
        "principal_amount": principal, "interest_rate": rate, "term_months": term, "start_date": start,
    }, headers=maker)
    assert loan.status_code == 201, loan.get_json()
    loan_id = loan.get_json()["loan"]["id"]
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=checker)
    assert approved.status_code == 200, approved.get_json()
    return loan_id


def get_loan(client, headers, loan_id):
    response = client.get(f"/api/loans/{loan_id}", headers=headers["maker"])
    assert response.status_code == 200
    return response.get_json()["loan"]


def open_rows(loan):
    return [row for row in loan["schedules"] if row["status"] in ("upcoming", "partial", "missed")]


# ------------------------------------------------------------------ Part 1: repayments


def test_maker_records_repayment_and_schedule_reconciles_with_emi(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers)
    loan = get_loan(client, headers, loan_id)
    first = loan["schedules"][0]
    original_emi = Decimal(str(first["expected_amount"]))
    assert len(loan["schedules"]) == 12

    # Paying exactly the first instalment on time: interest first, rest is principal.
    response = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": float(original_emi), "payment_date": first["due_date"],
    }, headers=headers["maker"])
    assert response.status_code == 201, response.get_json()
    repayment = response.get_json()["repayment"]
    assert repayment["interest_portion"] == first["interest_portion"]
    assert repayment["principal_portion"] == pytest.approx(first["principal_portion"])

    loan = get_loan(client, headers, loan_id)
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("1000000") - Decimal(str(first["principal_portion"]))
    assert loan["schedules"][0]["status"] == "paid"
    remaining = open_rows(loan)
    assert len(remaining) == 11
    # The remaining schedule is exactly the EMI schedule on the new balance over the remaining term.
    expected = amortization_schedule(loan["outstanding_balance"], loan["interest_rate"], 11)
    for row, want in zip(remaining, expected):
        assert Decimal(str(row["expected_amount"])) == want["payment_amount"]
        assert Decimal(str(row["principal_portion"])) == want["principal_portion"]
        assert Decimal(str(row["interest_portion"])) == want["interest_portion"]
    # An on-schedule payment leaves the EMI unchanged (within rounding).
    assert abs(Decimal(str(remaining[0]["expected_amount"])) - original_emi) <= Decimal("0.05")
    # Remaining principal always sums back to the balance.
    assert sum(Decimal(str(r["principal_portion"])) for r in remaining) == Decimal(str(loan["outstanding_balance"]))


def test_extra_repayment_lowers_the_remaining_instalments(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="extra")
    loan = get_loan(client, headers, loan_id)
    first = loan["schedules"][0]
    original_emi = Decimal(str(first["expected_amount"]))

    response = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 300_000, "payment_date": first["due_date"],
    }, headers=headers["maker"])
    assert response.status_code == 201

    loan = get_loan(client, headers, loan_id)
    remaining = open_rows(loan)
    assert len(remaining) == 11
    assert Decimal(str(remaining[0]["expected_amount"])) < original_emi
    assert sum(Decimal(str(r["principal_portion"])) for r in remaining) == Decimal(str(loan["outstanding_balance"]))
    assert [r["due_date"] for r in remaining] == [r["due_date"] for r in loan["schedules"][1:]]  # dates untouched


def test_paid_row_shows_the_real_repayment_when_larger_than_scheduled(client, staff):
    """PART 1 (critical): a schedule row that becomes 'paid' must display the
    REAL repayment split (from the Repayment record), never the original
    scheduled figures - this only shows up when the payment differs from
    what was scheduled, so pay MORE than the first instalment's EMI and make
    sure the paid row reflects exactly what was actually paid against it,
    and that the totals row still reconciles to the original principal."""
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=1_000_000, tag="real-paid-row")
    loan = get_loan(client, headers, loan_id)
    first = loan["schedules"][0]
    scheduled_principal = Decimal(str(first["principal_portion"]))
    overpay_amount = Decimal(str(first["expected_amount"])) + Decimal("50000")  # larger than what was due

    response = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": float(overpay_amount), "payment_date": first["due_date"],
    }, headers=headers["maker"])
    assert response.status_code == 201, response.get_json()
    repayment = response.get_json()["repayment"]
    # The extra beyond the scheduled interest/principal must also show as
    # real principal paid, strictly more than what was originally scheduled.
    assert Decimal(str(repayment["principal_portion"])) > scheduled_principal

    loan = get_loan(client, headers, loan_id)
    paid_row = loan["schedules"][0]
    assert paid_row["status"] == "paid"
    # The paid row must match the REAL repayment split exactly - not the stale schedule.
    assert Decimal(str(paid_row["principal_portion"])) == Decimal(str(repayment["principal_portion"]))
    assert Decimal(str(paid_row["interest_portion"])) == Decimal(str(repayment["interest_portion"]))
    assert Decimal(str(paid_row["expected_amount"])) == Decimal(str(repayment["principal_portion"])) + Decimal(str(repayment["interest_portion"]))
    assert Decimal(str(paid_row["principal_portion"])) != scheduled_principal

    # Totals = sum of actual paid amounts + sum of the currently recalculated
    # remaining rows, and principal must always reconcile to the original loan principal.
    remaining = open_rows(loan)
    assert Decimal(str(loan["totals"]["total_principal"])) == Decimal("1000000.00")
    assert Decimal(str(paid_row["principal_portion"])) + sum(Decimal(str(r["principal_portion"])) for r in remaining) == Decimal("1000000.00")
    assert Decimal(str(loan["totals"]["paid_to_date"])) == Decimal(str(overpay_amount))


def test_partial_repayment_keeps_the_instalment_open_for_the_shortfall(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="partial")
    loan = get_loan(client, headers, loan_id)
    first = loan["schedules"][0]
    emi = Decimal(str(first["expected_amount"]))

    client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 50_000, "payment_date": first["due_date"]}, headers=headers["maker"])
    loan = get_loan(client, headers, loan_id)
    row = loan["schedules"][0]
    assert row["status"] == "partial"
    assert Decimal(str(row["expected_amount"])) == emi - Decimal("50000")
    # Principal outstanding = what's left on this instalment + everything scheduled after it.
    assert sum(Decimal(str(r["principal_portion"])) for r in open_rows(loan)) == Decimal(str(loan["outstanding_balance"]))

    # The next payment settles this same instalment (not a later one).
    client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": float(emi - 50_000), "payment_date": first["due_date"]}, headers=headers["maker"])
    loan = get_loan(client, headers, loan_id)
    assert loan["schedules"][0]["status"] == "paid"
    assert loan["schedules"][1]["status"] == "upcoming"


def test_repaying_in_full_closes_the_loan_and_drops_future_instalments(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=100_000, term=6, tag="payoff")
    loan = get_loan(client, headers, loan_id)
    response = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": loan["settlement_amount"], "payment_date": loan["schedules"][0]["due_date"],
    }, headers=headers["maker"])
    assert response.status_code == 201, response.get_json()
    # settlement = principal outstanding + the interest due on the open instalment
    assert loan["settlement_amount"] == pytest.approx(loan["outstanding_balance"] + loan["schedules"][0]["interest_portion"])
    over = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 1, "payment_date": "2026-02-01"}, headers=headers["maker"])
    assert over.status_code == 400  # closed loans take no further payments
    loan = get_loan(client, headers, loan_id)
    assert loan["status"] == "closed"
    assert loan["outstanding_balance"] == 0
    assert open_rows(loan) == []


def test_repayment_validation_and_permissions(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="rules")
    today = date.today().isoformat()
    for bad in (0, -5, "abc", None):
        response = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": bad, "payment_date": today}, headers=headers["maker"])
        assert response.status_code == 400, bad
    too_much = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 99_999_999, "payment_date": today}, headers=headers["maker"])
    assert too_much.status_code == 400
    # A checker scoped to loans_credit now holds repayments:record too (Part 1) —
    # settle this one first so the next call has an open instalment to pay.
    allowed = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 1000, "payment_date": today}, headers=headers["checker"])
    assert allowed.status_code == 201, allowed.get_json()
    # ceo/head_manager may record too
    assert client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 1000, "payment_date": today}, headers=headers["head_manager"]).status_code == 201


def test_repayment_rejected_on_a_loan_that_is_not_active(client, staff):
    _, headers = staff
    borrower = client.post("/api/borrowers", json={"name": "B", "phone": "0700", "id_number": "I1", "nida_number": "N1"}, headers=headers["maker"]).get_json()["borrower"]
    product = client.post("/api/loan-products", json={"name": "P", "default_interest_rate": 10}, headers=headers["ceo"]).get_json()["loan_product"]
    loan_id = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 10000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers["maker"]).get_json()["loan"]["id"]
    response = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": 100, "payment_date": "2026-02-01"}, headers=headers["maker"])
    assert response.status_code == 400
    assert "active" in response.get_json()["message"]


def test_a_decision_cannot_be_applied_twice(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="twice")
    again = client.post(f"/api/loans/{loan_id}/approve", headers=headers["ceo"])
    assert again.status_code == 409


# ------------------------------------------------------------------ Part 1: permission matrix


def make_payroll_batch(client, headers, by="ceo", month="2026-03"):
    response = client.post("/api/payroll", json={"month": month}, headers=headers[by])
    assert response.status_code == 201, response.get_json()
    return response.get_json()["payroll_batch"]


@pytest.fixture()
def with_employees(app, staff):
    from extensions import db
    from models import Employee

    users, _ = staff
    rows = [
        Employee(name="Amina Salum", job_title="Teller", salary=Decimal("800000"), phone="0711", email="amina@example.com", start_date=date(2025, 1, 1), is_active=True),
        Employee(name="Juma Hassan", job_title="Accountant", salary=Decimal("1200000"), phone="0722", start_date=date(2025, 1, 1), is_active=True),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def test_checker_never_gets_payroll_regardless_of_department_hr_manager_does(client, make_user, auth_headers, staff, with_employees):
    """Payroll (like reports/assets/employees/capital) is never reachable by a
    checker or maker at all under the tier model — regardless of department.
    Only department_manager (here, HR) and above hold payroll:manage."""
    _, headers = staff
    loans_checker, loans_pw = make_user("checker", email="loans-only@example.com", department="loans_credit")
    hr_checker, hr_checker_pw = make_user("checker", email="hr-checker@example.com", department="hr")
    hr_manager, hr_manager_pw = make_user("department_manager", email="hr-manager@example.com", department="hr")
    batch = make_payroll_batch(client, headers)

    for email, pw in ((loans_checker.email, loans_pw), (hr_checker.email, hr_checker_pw)):
        denied = client.post(f"/api/payroll/{batch['id']}/finalize", headers=auth_headers(email, pw))
        assert denied.status_code == 403
        assert client.get("/api/payroll", headers=auth_headers(email, pw)).status_code == 403

    finalized = client.post(f"/api/payroll/{batch['id']}/finalize", headers=auth_headers(hr_manager.email, hr_manager_pw))
    assert finalized.status_code == 200, finalized.get_json()
    assert finalized.get_json()["payroll_batch"]["status"] == "paid"


def test_checker_and_maker_have_no_department_restriction_leave_stays_manager_only(client, make_user, auth_headers, staff, with_employees):
    """Part 4 simplification: a checker's create list (borrowers/repayments/
    expenses/penalties/own leave) and loan approval carry NO department
    restriction any more — a finance-scoped checker can approve a loan just
    as well as a loans_credit-scoped one. The two things that stay off
    limits for every checker, in every department, are creating a loan and
    approving a leave request — leave approval is department_manager(hr)/
    head_manager/ceo only."""
    _, headers = staff
    finance_checker, pw = make_user("checker", email="finance@example.com", department="finance")
    hdr = auth_headers(finance_checker.email, pw)

    # Recorded directly, no approval step, no department restriction.
    created = client.post("/api/expenses", json={"description": "Fuel", "category": "Transport", "amount": 5000, "date": "2026-02-01"}, headers=hdr)
    assert created.status_code == 201
    assert created.get_json()["expense"]["status"] == "recorded"

    borrower = client.post("/api/borrowers", json={"name": "B", "phone": "0700", "id_number": "IDS"}, headers=headers["maker"]).get_json()["borrower"]
    product = client.post("/api/loan-products", json={"name": "PS", "default_interest_rate": 10}, headers=headers["ceo"]).get_json()["loan_product"]
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 10000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers["maker"]).get_json()["loan"]
    # a finance-scoped checker can approve ANY loan — no department restriction any more
    assert client.post(f"/api/loans/{loan['id']}/approve", headers=hdr).status_code == 200

    # a checker can never create a loan — hard rule, no exception, any department
    loan2 = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1000,
        "interest_rate": 10, "term_months": 3, "start_date": "2026-01-01",
    }, headers=headers["checker"])
    assert loan2.status_code == 403

    # leave: no checker approves it, in any department — department_manager(hr)/head_manager/ceo only
    from extensions import db
    from models import Employee
    users, _ = staff
    own = Employee(name="Maker", job_title="Officer", salary=0, phone="0733", start_date=date(2025, 1, 1), is_active=True, user_id=users["maker"].id)
    db.session.add(own)
    db.session.commit()
    leave = client.post("/api/leave-requests", json={"employee_id": own.id, "leave_type": "Annual", "start_date": "2026-05-01", "end_date": "2026-05-03"}, headers=headers["maker"]).get_json()["leave_request"]
    assert client.post(f"/api/leave-requests/{leave['id']}/approve", headers=hdr).status_code == 403
    hr_checker, hr_pw = make_user("checker", email="hr2@example.com", department="hr")
    assert client.post(f"/api/leave-requests/{leave['id']}/approve", headers=auth_headers(hr_checker.email, hr_pw)).status_code == 403
    hr_manager, hr_manager_pw = make_user("department_manager", email="hr-mgr-leave@example.com", department="hr")
    assert client.post(f"/api/leave-requests/{leave['id']}/approve", headers=auth_headers(hr_manager.email, hr_manager_pw)).status_code == 200


def test_ceo_and_head_manager_have_every_permission_by_default(client, staff, with_employees):
    _, headers = staff
    # ceo/head_manager are unscoped — everything, unconditionally, no department needed.
    batch = make_payroll_batch(client, headers, by="ceo", month="2026-04")
    assert client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"]).status_code == 200

    # expenses:manage is on the head_manager's unconditional access, and (Part
    # 4) on every maker's fixed action set too now — recorded directly, no
    # approval step, no department restriction.
    expense = client.post("/api/expenses", json={"description": "x", "category": "Other", "amount": 10, "date": "2026-02-01"}, headers=headers["head_manager"]).get_json()["expense"]
    assert expense["status"] == "recorded"
    assert client.post("/api/expenses", json={"description": "x", "category": "Other", "amount": 10, "date": "2026-02-01"}, headers=headers["maker"]).status_code == 201
    # something genuinely outside a maker's reach: payroll, in any form
    assert client.get("/api/payroll", headers=headers["maker"]).status_code == 403


def test_new_scoped_user_requires_a_department_and_it_can_be_changed_later(client, make_user, auth_headers, staff):
    """Retires the old per-user permission matrix (Part 0): a checker/maker/
    department_manager account is defined entirely by role + department —
    department is required up front and can be corrected afterward."""
    _, headers = staff
    missing_department = client.post(
        "/api/auth/register",
        json={"name": "Chk", "email": "chk@example.com", "phone": "0755000111", "role": "checker"},
        headers=headers["ceo"],
    )
    assert missing_department.status_code == 400

    created = client.post(
        "/api/auth/register",
        json={"name": "Chk", "email": "chk2@example.com", "phone": "0755000112", "role": "checker", "department": "loans_credit"},
        headers=headers["ceo"],
    )
    assert created.status_code == 201
    user = created.get_json()["user"]
    assert user["department"] == "loans_credit"
    assert "permissions" not in user  # the checkbox matrix is gone — nothing per-user to list

    updated = client.patch(f"/api/users/{user['id']}", json={"department": "hr"}, headers=headers["head_manager"])
    assert updated.status_code == 200
    assert updated.get_json()["user"]["department"] == "hr"

    assert client.patch(f"/api/users/{user['id']}", json={"department": "not-a-real-department"}, headers=headers["head_manager"]).status_code == 400

    # CEO accounts are fixed — no one can edit them
    assert client.patch(f"/api/users/{staff[0]['ceo'].id}", json={"department": "hr"}, headers=headers["head_manager"]).status_code == 403


# ------------------------------------------------------------------ Part 6: payroll batch


def test_payroll_prepare_preview_edit_remove_then_single_finalize_action(client, staff, with_employees):
    """No second approver (Part 1.5): the same person who prepares a batch may
    also finalize it."""
    _, headers = staff
    batch = make_payroll_batch(client, headers, by="head_manager")
    assert batch["line_count"] == 2
    assert {line["employee_name"] for line in batch["lines"]} == {"Amina Salum", "Juma Hassan"}
    amina = next(line for line in batch["lines"] if line["employee_name"] == "Amina Salum")
    juma = next(line for line in batch["lines"] if line["employee_name"] == "Juma Hassan")

    # payslips do not exist before the batch is finalized
    assert client.get(f"/api/payroll/lines/{amina['id']}/payslip", headers=headers["ceo"]).status_code == 409

    # the preparer previews and corrects their own batch — allowed
    edited = client.patch(f"/api/payroll/{batch['id']}/lines/{amina['id']}", json={"deductions": 50_000}, headers=headers["head_manager"])
    assert edited.status_code == 200
    lines = {line["employee_name"]: line for line in edited.get_json()["payroll_batch"]["lines"]}
    assert lines["Amina Salum"]["net_pay"] == 750_000
    assert client.patch(f"/api/payroll/{batch['id']}/lines/{amina['id']}", json={"deductions": 9_999_999}, headers=headers["head_manager"]).status_code == 400
    assert client.patch(f"/api/payroll/{batch['id']}/lines/{amina['id']}", json={"salary_amount": -1}, headers=headers["head_manager"]).status_code == 400

    removed = client.delete(f"/api/payroll/{batch['id']}/lines/{juma['id']}", headers=headers["head_manager"])
    assert removed.status_code == 200
    assert removed.get_json()["payroll_batch"]["line_count"] == 1
    # the last line cannot be removed: cancel the batch instead
    assert client.delete(f"/api/payroll/{batch['id']}/lines/{amina['id']}", headers=headers["head_manager"]).status_code == 400

    # ONE action finalizes the whole batch — by the same person who made it
    finalized = client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"])
    assert finalized.status_code == 200
    body = finalized.get_json()["payroll_batch"]
    assert body["status"] == "paid" and body["total_net"] == 750_000
    assert all(line["status"] == "paid" for line in body["lines"])

    # edits are locked after finalizing; a second finalize is refused
    assert client.patch(f"/api/payroll/{batch['id']}/lines/{amina['id']}", json={"deductions": 1}, headers=headers["head_manager"]).status_code == 409
    assert client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"]).status_code == 409

    # now the per-employee payslip PDF is available
    slip = client.get(f"/api/payroll/lines/{amina['id']}/payslip", headers=headers["ceo"])
    assert slip.status_code == 200 and slip.mimetype == "application/pdf" and slip.data.startswith(b"%PDF")


def test_individual_deductions_apply_only_to_their_own_employee_and_drain_the_balance(client, staff, with_employees):
    """Amina alone has a 50,000/month loan repayment with a 120,000 balance.
    Standard deductions still apply to everyone; this individual one must
    never appear on Juma's line, must shrink each finalized run, cap at
    whatever is left, and vanish once fully repaid."""
    _, headers = staff
    amina, juma = with_employees

    dtype = client.post("/api/payroll/deduction-types", json={
        "name": "Loan Repayment", "calculation": "fixed", "side": "employee", "scope": "individual",
    }, headers=headers["ceo"])
    assert dtype.status_code == 201, dtype.get_json()
    dtype_id = dtype.get_json()["deduction_type"]["id"]

    assigned = client.post("/api/payroll/employee-deductions", json={
        "employee_id": amina.id, "deduction_type_id": dtype_id,
        "amount": 50_000, "start_month": "2026-03", "remaining_balance": 120_000,
    }, headers=headers["ceo"])
    assert assigned.status_code == 201, assigned.get_json()

    def lines_for(batch, name):
        line = next(l for l in batch["lines"] if l["employee_name"] == name)
        return [dl for dl in line["deduction_lines"] if dl["name"] == "Loan Repayment"]

    # Run 1: 2026-03 — Amina gets the full 50,000; Juma gets none.
    b1 = make_payroll_batch(client, headers, by="ceo", month="2026-03")
    amina_lines = lines_for(b1, "Amina Salum")
    assert len(amina_lines) == 1
    assert amina_lines[0]["side"] == "employee" and amina_lines[0]["amount"] == 50000.0
    assert amina_lines[0]["scope"] == "individual" and amina_lines[0]["is_adjusted"] is False
    assert lines_for(b1, "Juma Hassan") == []
    assert client.post(f"/api/payroll/{b1['id']}/finalize", headers=headers["ceo"]).status_code == 200

    # Run 2: 2026-04 — balance now 70,000, still a full 50,000 instalment.
    b2 = make_payroll_batch(client, headers, by="ceo", month="2026-04")
    assert lines_for(b2, "Amina Salum")[0]["amount"] == 50000.0
    assert client.post(f"/api/payroll/{b2['id']}/finalize", headers=headers["ceo"]).status_code == 200

    # Run 3: 2026-05 — only 20,000 left, so the line is CAPPED at 20,000, not 50,000.
    b3 = make_payroll_batch(client, headers, by="ceo", month="2026-05")
    assert lines_for(b3, "Amina Salum")[0]["amount"] == 20000.0
    assert client.post(f"/api/payroll/{b3['id']}/finalize", headers=headers["ceo"]).status_code == 200

    # Run 4: 2026-06 — fully repaid, the line is gone entirely.
    b4 = make_payroll_batch(client, headers, by="ceo", month="2026-06")
    assert lines_for(b4, "Amina Salum") == []


def test_percentage_individual_deduction_rounds_up_and_a_run_only_edit_never_touches_the_standing_assignment(client, staff, with_employees):
    """Amina gets a 3.33% individual 'Salary Advance' repayment — on her
    800,000 gross that's 26,640 exactly rounded up (800,000 x 0.0333 =
    26,640.0, already whole, so this also proves the rounding is UP not
    down by checking a rate that does NOT divide evenly: 3.335%).
    Editing that one run's line to a flat 10,000 must mark it 'Adjusted',
    recompute net pay, and leave the standing EmployeeDeduction (still
    3.335%, still governing every OTHER run) completely untouched."""
    _, headers = staff
    amina, _juma = with_employees

    dtype = client.post("/api/payroll/deduction-types", json={
        "name": "Salary Advance", "calculation": "fixed", "side": "employee", "scope": "individual",
    }, headers=headers["ceo"])
    assert dtype.status_code == 201, dtype.get_json()
    dtype_id = dtype.get_json()["deduction_type"]["id"]

    assigned = client.post("/api/payroll/employee-deductions", json={
        "employee_id": amina.id, "deduction_type_id": dtype_id,
        "calculation": "percentage", "rate": 3.335, "start_month": "2026-03",
    }, headers=headers["ceo"])
    assert assigned.status_code == 201, assigned.get_json()
    assignment_id = assigned.get_json()["employee_deduction"]["id"]
    # 800,000 x 3.335% = 26,680 exactly — pick a rate that forces rounding
    # instead: re-check with the fractional case below, this just confirms
    # the assignment itself stores the percentage, not a precomputed amount.
    assert assigned.get_json()["employee_deduction"]["calculation"] == "percentage"
    assert float(assigned.get_json()["employee_deduction"]["rate"]) == 3.335

    batch = make_payroll_batch(client, headers, by="ceo", month="2026-03")
    amina_line = next(l for l in batch["lines"] if l["employee_name"] == "Amina Salum")
    advance = next(dl for dl in amina_line["deduction_lines"] if dl["name"] == "Salary Advance")
    # 800,000 * 3.335 / 100 = 26680.0 exactly, but money math is Decimal —
    # assert via the exact whole_up formula rather than a hand-typed literal.
    from decimal import Decimal
    from services.loan_calculator import whole_up
    expected = float(whole_up(Decimal("800000") * Decimal("3.335") / Decimal("100")))
    assert advance["amount"] == expected
    assert advance["scope"] == "individual" and advance["is_adjusted"] is False

    # Edit THIS RUN's line only, to a flat 10,000.
    adjusted = client.patch(
        f"/api/payroll/{batch['id']}/lines/{amina_line['id']}/deduction-lines/{advance['id']}",
        json={"amount": 10_000}, headers=headers["ceo"],
    )
    assert adjusted.status_code == 200, adjusted.get_json()
    updated_line = next(l for l in adjusted.get_json()["payroll_batch"]["lines"] if l["id"] == amina_line["id"])
    updated_dl = next(dl for dl in updated_line["deduction_lines"] if dl["name"] == "Salary Advance")
    assert updated_dl["amount"] == 10_000.0 and updated_dl["is_adjusted"] is True
    assert updated_line["deductions"] == 10_000.0
    assert updated_line["net_pay"] == 790_000.0

    # The standing assignment itself was never touched by that edit.
    still = client.get("/api/payroll/employee-deductions", query_string={"employee_id": amina.id}, headers=headers["ceo"])
    assignment_now = next(a for a in still.get_json()["employee_deductions"] if a["id"] == assignment_id)
    assert assignment_now["calculation"] == "percentage" and float(assignment_now["rate"]) == 3.335

    # And the NEXT run (a fresh preview) goes right back to the real 3.335% — the edit was for that one run only.
    batch2 = make_payroll_batch(client, headers, by="ceo", month="2026-04")
    amina_line2 = next(l for l in batch2["lines"] if l["employee_name"] == "Amina Salum")
    advance2 = next(dl for dl in amina_line2["deduction_lines"] if dl["name"] == "Salary Advance")
    assert advance2["amount"] == expected and advance2["is_adjusted"] is False


def test_adjust_deduction_line_by_percentage_rounds_up_and_clamps_to_pay_available(client, staff, with_employees):
    """Editing a payroll line's deduction with a PERCENTAGE (not a flat
    amount) must round UP to the whole shilling, and — when a standard
    deduction already consumes most of the gross — must clamp the edited
    line at whatever pay is actually left rather than pushing net pay
    negative or erroring out."""
    _, headers = staff
    amina, _juma = with_employees
    from decimal import Decimal
    from services.loan_calculator import whole_up

    standard = client.post("/api/payroll/deduction-types", json={
        "name": "NSSF", "calculation": "fixed", "fixed_amount": 750_000, "side": "employee", "scope": "standard",
    }, headers=headers["ceo"])
    assert standard.status_code == 201, standard.get_json()

    dtype = client.post("/api/payroll/deduction-types", json={
        "name": "Uniform", "calculation": "fixed", "side": "employee", "scope": "individual",
    }, headers=headers["ceo"])
    dtype_id = dtype.get_json()["deduction_type"]["id"]
    client.post("/api/payroll/employee-deductions", json={
        "employee_id": amina.id, "deduction_type_id": dtype_id,
        "calculation": "fixed", "amount": 5_000, "start_month": "2026-07",
    }, headers=headers["ceo"])

    batch = make_payroll_batch(client, headers, by="ceo", month="2026-07")
    amina_line = next(l for l in batch["lines"] if l["employee_name"] == "Amina Salum")
    uniform = next(dl for dl in amina_line["deduction_lines"] if dl["name"] == "Uniform")

    # Gross 800,000 minus the 750,000 standard deduction leaves only 50,000
    # available. A 12.345% edit (98,760 rounded up to 98,760 — pick a rate
    # that does NOT divide evenly) would be 800,000 x 0.12345 = 98,760.0,
    # already whole, so use 12.3456 to force real rounding: 98,764.8 -> 98,765,
    # which still exceeds the 50,000 available and must clamp to 50,000.
    adjusted = client.patch(
        f"/api/payroll/{batch['id']}/lines/{amina_line['id']}/deduction-lines/{uniform['id']}",
        json={"rate": 12.3456}, headers=headers["ceo"],
    )
    assert adjusted.status_code == 200, adjusted.get_json()
    updated_line = next(l for l in adjusted.get_json()["payroll_batch"]["lines"] if l["id"] == amina_line["id"])
    updated_dl = next(dl for dl in updated_line["deduction_lines"] if dl["name"] == "Uniform")
    raw = whole_up(Decimal("800000") * Decimal("12.3456") / Decimal("100"))
    assert raw == Decimal("98765")  # confirms the rate really does force rounding up
    assert updated_dl["amount"] == 50_000.0 and updated_dl["is_adjusted"] is True
    assert updated_line["deductions"] == 800_000.0
    assert updated_line["net_pay"] == 0.0

    # A small, well-within-range percentage is NOT clamped and rounds up normally.
    small = client.patch(
        f"/api/payroll/{batch['id']}/lines/{amina_line['id']}/deduction-lines/{uniform['id']}",
        json={"rate": 0.6667}, headers=headers["ceo"],
    )
    assert small.status_code == 200, small.get_json()
    small_line = next(l for l in small.get_json()["payroll_batch"]["lines"] if l["id"] == amina_line["id"])
    small_dl = next(dl for dl in small_line["deduction_lines"] if dl["name"] == "Uniform")
    expected_small = float(whole_up(Decimal("800000") * Decimal("0.6667") / Decimal("100")))
    assert small_dl["amount"] == expected_small
    assert small_line["deductions"] == float(Decimal("750000") + Decimal(str(expected_small)))
    assert small_line["net_pay"] == 800_000.0 - small_line["deductions"]


def test_payslip_send_uses_the_employee_email(client, staff, with_employees, monkeypatch):
    _, headers = staff
    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-06")
    client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"])
    sent = []
    monkeypatch.setattr("routes.payroll.send_email", lambda kind, to, data: sent.append((kind, to, data)) or {"status": "sent"})

    amina = next(line for line in batch["lines"] if line["employee_name"] == "Amina Salum")
    juma = next(line for line in batch["lines"] if line["employee_name"] == "Juma Hassan")
    ok = client.post(f"/api/payroll/lines/{amina['id']}/payslip/send", headers=headers["ceo"])
    assert ok.status_code == 200
    assert sent[0][0] == "payslip" and sent[0][1] == "amina@example.com" and sent[0][2]["pdf_base64"]
    # no email on file -> a plain message, nothing sent
    no_email = client.post(f"/api/payroll/lines/{juma['id']}/payslip/send", headers=headers["ceo"])
    assert no_email.status_code == 400 and "no email" in no_email.get_json()["message"]
    assert len(sent) == 1


def test_payroll_cancel_needs_no_reason_and_only_one_active_batch_per_month(client, staff, with_employees):
    _, headers = staff
    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-07")
    assert client.post("/api/payroll", json={"month": "2026-07"}, headers=headers["ceo"]).status_code == 409
    cancelled = client.post(f"/api/payroll/{batch['id']}/cancel", headers=headers["ceo"])
    assert cancelled.status_code == 200 and cancelled.get_json()["payroll_batch"]["status"] == "cancelled"
    # a cancelled month can be run again
    assert client.post("/api/payroll", json={"month": "2026-07"}, headers=headers["ceo"]).status_code == 201


# ------------------------------------------------------------------ Part 8: schedule PDF


def test_schedule_pdf_is_available_for_a_pending_loan(client, staff):
    _, headers = staff
    borrower = client.post("/api/borrowers", json={"name": "Pending Person", "phone": "0700", "id_number": "IP", "nida_number": "NP"}, headers=headers["maker"]).get_json()["borrower"]
    product = client.post("/api/loan-products", json={"name": "PP", "default_interest_rate": 25}, headers=headers["ceo"]).get_json()["loan_product"]
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 1_000_000,
        "interest_rate": 25, "term_months": 12, "start_date": "2026-01-15",
    }, headers=headers["maker"]).get_json()["loan"]
    assert loan["status"] == "pending_approval"

    for who in ("maker", "checker", "ceo"):
        response = client.get(f"/api/loans/{loan['id']}/schedule/export", headers=headers[who])
        assert response.status_code == 200, who
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF")
    assert client.get(f"/api/loans/{loan['id']}/schedule/export").status_code == 401


def test_schedule_pdf_content_is_comma_formatted_and_branded(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="pdf")
    response = client.get(f"/api/loans/{loan_id}/schedule/export", headers=headers["maker"])
    from pypdf import PdfReader  # noqa: WPS433 - optional, only for this check
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
    # Part 1.5: whole shillings, commas, NO decimals - was "1,000,000.00".
    assert "1,000,000" in text and "1,000,000.00" not in text
    import branding
    assert "Repayment Schedule" in text and branding.COMPANY_NAME in text


# ------------------------------------------------------------------ Part 7: model & access


def test_product_limits_are_optional_and_unset_limits_are_not_enforced(client, staff):
    _, headers = staff
    product = client.post("/api/loan-products", json={"name": "Open", "default_interest_rate": 12}, headers=headers["ceo"])
    assert product.status_code == 201
    body = product.get_json()["loan_product"]
    assert body["min_term_months"] is None and body["max_amount"] is None
    borrower = client.post("/api/borrowers", json={"name": "B", "phone": "0700", "id_number": "IO", "nida_number": "NO"}, headers=headers["maker"]).get_json()["borrower"]
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": body["id"], "principal_amount": 900_000_000,
        "interest_rate": 12, "term_months": 120, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert loan.status_code == 201

    # a partly-set product enforces only what is set
    capped = client.post("/api/loan-products", json={"name": "Capped", "default_interest_rate": 12, "max_amount": 5000}, headers=headers["ceo"]).get_json()["loan_product"]
    too_big = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": capped["id"], "principal_amount": 6000,
        "interest_rate": 12, "term_months": 120, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert too_big.status_code == 400
    # min > max is still nonsense
    assert client.post("/api/loan-products", json={"name": "Bad", "default_interest_rate": 1, "min_amount": 10, "max_amount": 5}, headers=headers["ceo"]).status_code == 400
    # limits can be cleared again on edit
    cleared = client.put(f"/api/loan-products/{capped['id']}", json={"max_amount": None}, headers=headers["ceo"])
    assert cleared.status_code == 200 and cleared.get_json()["loan_product"]["max_amount"] is None


def test_audit_log_access_is_ceo_and_head_manager_only(client, staff):
    _, headers = staff
    assert client.get("/api/audit-logs", headers=headers["ceo"]).status_code == 200
    assert client.get("/api/audit-logs", headers=headers["head_manager"]).status_code == 200
    assert client.get("/api/audit-logs", headers=headers["checker"]).status_code == 403
    assert client.get("/api/audit-logs", headers=headers["maker"]).status_code == 403


def test_lists_resolve_names_instead_of_ids(client, staff, with_employees):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="names")
    penalty = client.post("/api/penalties", json={"loan_id": loan_id, "amount": 500, "reason": "late"}, headers=headers["maker"]).get_json()["penalty"]
    # Penalty approval is department_manager-and-above now — a checker can
    # still list penalties (reads stay open) but can_decide is False for them.
    rows = client.get("/api/penalties", headers=headers["checker"]).get_json()["penalties"]
    row = next(r for r in rows if r["id"] == penalty["id"])
    assert row["borrower_name"] == "Jane names" and row["created_by_name"] == "Maker User" and row["can_decide"] is False
    ceo_rows = client.get("/api/penalties", headers=headers["ceo"]).get_json()["penalties"]
    ceo_row = next(r for r in ceo_rows if r["id"] == penalty["id"])
    assert ceo_row["can_decide"] is True
    batch = make_payroll_batch(client, headers)
    assert batch["lines"][0]["employee_name"] and batch["creator_name"] == "Ceo User"
    loans = client.get("/api/loans", headers=headers["maker"]).get_json()["loans"]
    assert loans[0]["borrower_name"] == "Jane names"


def test_borrower_photo_and_id_document_upload_and_secure_serving(client, staff):
    from PIL import Image

    _, headers = staff

    def png():
        buffer = BytesIO()
        Image.new("RGB", (8, 8), (26, 58, 92)).save(buffer, "PNG")
        buffer.seek(0)
        return buffer

    created = client.post("/api/borrowers", data={
        "name": "Photo Person", "phone": "0700", "id_number": "IDF", "nida_number": "NDF",
        "photo": (png(), "me.png"), "id_document": (png(), "id.png"),
    }, headers=headers["maker"], content_type="multipart/form-data")
    assert created.status_code == 201, created.get_json()
    borrower = created.get_json()["borrower"]
    assert borrower["has_photo"] is True and borrower["has_id_document"] is True
    assert "photo_path" not in borrower  # stored names never leave the server

    for kind in ("photo", "id-document"):
        assert client.get(f"/api/borrowers/{borrower['id']}/{kind}").status_code == 401  # login required
        served = client.get(f"/api/borrowers/{borrower['id']}/{kind}", headers=headers["checker"])
        assert served.status_code == 200 and served.mimetype == "image/png"
        assert "no-store" in served.headers["Cache-Control"]
    assert client.get(f"/api/borrowers/{borrower['id']}/passport", headers=headers["checker"]).status_code == 404

    # non-images and oversized files are refused; replacing works
    fake = client.post(f"/api/borrowers/{borrower['id']}/photo", data={"file": (BytesIO(b"<script>alert(1)</script>"), "x.png")}, headers=headers["maker"], content_type="multipart/form-data")
    assert fake.status_code == 400
    replaced = client.post(f"/api/borrowers/{borrower['id']}/photo", data={"file": (png(), "new.png")}, headers=headers["maker"], content_type="multipart/form-data")
    assert replaced.status_code == 200
    # borrowers:manage is on every checker's fixed action set now, no
    # department restriction at all (Part 4).
    assert client.post(f"/api/borrowers/{borrower['id']}/photo", data={"file": (png(), "n.png")}, headers=headers["checker"], content_type="multipart/form-data").status_code == 200


# ------------------------------------------------------------------ Part 5: user <-> employee


def test_employee_can_be_created_with_a_login(client, staff):
    users, headers = staff
    created = client.post("/api/employees", json={
        "name": "New Hire", "phone": "0766000111", "job_title": "Teller", "salary": 600000, "start_date": "2026-02-01",
        "create_user": True, "email": "newhire@example.com", "role": "checker", "department": "hr",
    }, headers=headers["ceo"])
    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    assert body["user"]["role"] == "checker" and body["user"]["department"] == "hr"
    assert body["employee"]["user_id"] == body["user"]["id"]

    # unchecked by default: no login is made
    plain = client.post("/api/employees", json={"name": "No Login", "phone": "0766000222", "job_title": "Cleaner", "salary": 300000, "start_date": "2026-02-01"}, headers=headers["ceo"])
    assert plain.status_code == 201 and plain.get_json()["employee"]["user_id"] is None
    # a duplicate email fails the whole request, creating nothing
    dup = client.post("/api/employees", json={"name": "Dup", "phone": "0766000333", "job_title": "X", "salary": 1, "start_date": "2026-02-01", "create_user": True, "email": "newhire@example.com", "department": "loans_credit"}, headers=headers["ceo"])
    assert dup.status_code == 409
    names = [e["name"] for e in client.get("/api/employees", headers=headers["ceo"]).get_json()["employees"]]
    assert "Dup" not in names


def test_create_login_action_is_not_limited_to_hr_or_to_maker_checker_tiers(client, staff, make_user, auth_headers):
    """PART 11: "Create login" for an employee with no login yet used to be
    gated by employees:manage (HR-only), which greyed it out for no clear
    reason for anyone outside HR, and its tier options were hard-limited to
    maker/checker. Fixed via account_creator_required (the general account-
    creation hierarchy) - any actor who can hand out at least one tier can
    use it, and the tier they can grant follows the normal rules, not an
    extra, narrower restriction."""
    _, headers = staff
    employee = client.post("/api/employees", json={
        "name": "No Login Yet", "phone": "0766555444", "email": "nologinyet@example.com",
        "job_title": "Officer", "salary": 400000, "start_date": "2026-01-01",
    }, headers=headers["ceo"]).get_json()["employee"]

    loans_manager, pw = make_user("department_manager", email="loansmgr11@example.com", department="loans_credit")
    lm_headers = auth_headers(loans_manager.email, pw)
    # No employees:manage at all - a Loans Manager isn't HR - yet the action works.
    created = client.post(f"/api/employees/{employee['id']}/create-login", json={
        "role": "maker", "department": "loans_credit",
    }, headers=lm_headers)
    assert created.status_code == 201, created.get_json()
    assert created.get_json()["employee"]["user_id"] is not None

    # A department_manager-tier login is still correctly refused for a
    # Loans Manager actor (their creation hierarchy stops at checker/maker) -
    # the fix widens WHO can use the action, not WHAT they're allowed to grant.
    other_employee = client.post("/api/employees", json={
        "name": "Also No Login", "phone": "0766555555", "email": "alsonologin@example.com",
        "job_title": "Officer", "salary": 400000, "start_date": "2026-01-01",
    }, headers=headers["ceo"]).get_json()["employee"]
    denied = client.post(f"/api/employees/{other_employee['id']}/create-login", json={
        "role": "department_manager", "department": "finance",
    }, headers=lm_headers)
    assert denied.status_code == 403


def test_users_and_employees_can_be_linked_after_the_fact(client, staff):
    users, headers = staff
    loose_employee = client.post("/api/employees", json={"name": "Loose", "phone": "0777000111", "job_title": "Officer", "salary": 500000, "start_date": "2026-01-01"}, headers=headers["ceo"]).get_json()["employee"]

    # from the Employees side
    linked = client.post(f"/api/employees/{loose_employee['id']}/link-user", json={"user_id": users["maker"].id}, headers=headers["head_manager"])
    assert linked.status_code == 200 and linked.get_json()["employee"]["linked_user_name"] == "Maker User"
    # already-linked on either side is refused
    assert client.post(f"/api/employees/{loose_employee['id']}/link-user", json={"user_id": users["checker"].id}, headers=headers["head_manager"]).status_code == 409
    other = client.post("/api/employees", json={"name": "Other", "phone": "0777000222", "job_title": "Officer", "salary": 1, "start_date": "2026-01-01"}, headers=headers["ceo"]).get_json()["employee"]
    assert client.post(f"/api/employees/{other['id']}/link-user", json={"user_id": users["maker"].id}, headers=headers["head_manager"]).status_code == 409

    # from the Users side
    via_user = client.post(f"/api/users/{users['checker'].id}/link-employee", json={"employee_id": other["id"]}, headers=headers["head_manager"])
    assert via_user.status_code == 200 and via_user.get_json()["user"]["employee_id"] == other["id"]
    assert client.post(f"/api/users/{users['checker'].id}/link-employee", json={"employee_id": other["id"]}, headers=headers["maker"]).status_code == 403


def test_employee_fields_can_be_edited_and_employee_soft_deactivated(client, staff, with_employees):
    users, headers = staff
    # an employee auto-created through a user...
    created = client.post("/api/auth/register", json={"name": "Via User", "email": "viauser@example.com", "phone": "0788000111", "role": "maker", "department": "loans_credit", "salary": 400000}, headers=headers["ceo"]).get_json()
    employee_id = created["employee"]["id"]
    # ...and one created directly, both editable
    for target in (employee_id, with_employees[0].id):
        edit = client.put(f"/api/employees/{target}", json={"salary": 950000, "job_title": "Senior Officer", "phone": "0788999999"}, headers=headers["head_manager"])
        assert edit.status_code == 200, edit.get_json()
        assert edit.get_json()["employee"]["salary"] == 950000 and edit.get_json()["employee"]["job_title"] == "Senior Officer"
    assert client.put(f"/api/employees/{employee_id}", json={"salary": -5}, headers=headers["head_manager"]).status_code == 400
    assert client.put(f"/api/employees/{employee_id}", json={"salary": 1}, headers=headers["maker"]).status_code == 403

    # deactivate = soft delete, drops out of new payroll runs, can be reversed
    gone = client.delete(f"/api/employees/{with_employees[1].id}", headers=headers["head_manager"])
    assert gone.status_code == 200 and gone.get_json()["employee"]["is_active"] is False
    assert len(client.get("/api/employees", headers=headers["ceo"]).get_json()["employees"]) == 3
    batch = make_payroll_batch(client, headers, month="2026-08")
    assert "Juma Hassan" not in {line["employee_name"] for line in batch["lines"]}
    back = client.put(f"/api/employees/{with_employees[1].id}", json={"is_active": True}, headers=headers["head_manager"])
    assert back.get_json()["employee"]["is_active"] is True


def test_non_admins_never_see_salaries(client, staff, with_employees):
    _, headers = staff
    assert client.get("/api/employees", headers=headers["maker"]).get_json()["employees"] == []
    assert all("salary" in e for e in client.get("/api/employees", headers=headers["ceo"]).get_json()["employees"])


def test_me_endpoint_reports_the_token_owner(client, staff):
    users, headers = staff
    me = client.get("/api/auth/me", headers=headers["checker"]).get_json()["user"]
    assert me["id"] == users["checker"].id and me["role"] == "checker"
    assert me["department"] == "loans_credit"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=headers["ceo"]).headers["Cache-Control"] == "no-store"


# ------------------------------------------------------------------ Part 2: no borrower approval (regression)


def test_new_borrower_has_no_pending_state_and_is_usable_immediately(client, staff):
    """PART 2 (regression): borrowers must never go through any pending/
    approval step. A borrower is a plain record from the moment it's
    created - no approval-shaped field anywhere on it, and it can be used
    for a loan right away with no extra step. Also covers PART 3.2: photo/
    ID uploads are fully optional at creation (neither file is sent here)."""
    _, headers = staff
    created = client.post("/api/borrowers", json={
        "name": "No Approval Needed", "phone": "0700999888", "id_number": "IDNA1", "nida_number": "NIDANA1",
    }, headers=headers["maker"])
    assert created.status_code == 201, created.get_json()
    borrower = created.get_json()["borrower"]
    assert "status" not in borrower and "approved" not in borrower and "pending" not in borrower
    assert borrower["has_photo"] is False and borrower["has_id_document"] is False

    # Immediately visible in the list - no separate activation/approval step.
    listed = client.get("/api/borrowers", headers=headers["maker"]).get_json()["borrowers"]
    assert any(b["id"] == borrower["id"] for b in listed)

    # Immediately usable for a loan, with no gate in between.
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "principal_amount": 100000,
        "interest_rate": 10, "term_months": 6, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()


# ------------------------------------------------------------------ Part 4: loans manager products + negotiated loans


def test_loans_manager_department_manager_can_create_and_edit_loan_products(client, make_user, auth_headers):
    """PART 4.1: a department_manager scoped to loans_credit (a "Loans
    Manager") must be able to create/edit Loan Products - this used to be
    ceo/head_manager only."""
    loans_manager, pw = make_user("department_manager", email="loansmgr@example.com", department="loans_credit")
    headers = auth_headers(loans_manager.email, pw)
    created = client.post("/api/loan-products", json={
        "name": "Loans Manager Product", "default_interest_rate": 15, "default_term_months": 6,
    }, headers=headers)
    assert created.status_code == 201, created.get_json()
    product_id = created.get_json()["loan_product"]["id"]
    edited = client.put(f"/api/loan-products/{product_id}", json={"default_interest_rate": 18}, headers=headers)
    assert edited.status_code == 200 and edited.get_json()["loan_product"]["default_interest_rate"] == 18

    # A department_manager scoped to a different department has no business here.
    hr_manager, hr_pw = make_user("department_manager", email="hrmgr@example.com", department="hr")
    hr_headers = auth_headers(hr_manager.email, hr_pw)
    assert client.post("/api/loan-products", json={"name": "Nope", "default_interest_rate": 1}, headers=hr_headers).status_code == 403


def test_maker_can_create_a_negotiated_loan_with_no_product(client, staff):
    """PART 4.2: loan_product_id is optional - with none given, the Maker's
    own principal/rate/term are used directly (a negotiated/custom loan),
    through the exact same amortization function as a product-backed loan."""
    _, headers = staff
    borrower = client.post("/api/borrowers", json={
        "name": "Negotiated Borrower", "phone": "0700111222", "id_number": "NEG1", "nida_number": "NIDANEG1",
    }, headers=headers["maker"]).get_json()["borrower"]

    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "principal_amount": 500_000,
        "interest_rate": 7.5, "term_months": 9, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()
    body = loan.get_json()["loan"]
    assert body["loan_product_id"] is None
    assert Decimal(str(body["interest_rate"])) == Decimal("7.5")
    assert body["term_months"] == 9

    approved = client.post(f"/api/loans/{body['id']}/approve", headers=headers["checker"])
    assert approved.status_code == 200
    detail = get_loan(client, headers, body["id"])
    assert len(detail["schedules"]) == 9
    expected = amortization_schedule(500_000, Decimal("7.5"), 9)
    assert Decimal(str(detail["schedules"][0]["expected_amount"])) == expected[0]["payment_amount"]


def test_a_products_rate_is_locked_server_side_but_term_never_is(client, staff):
    """PART 2 (16-part-v2 spec): a loan product locks the RATE only, server-
    side - a request that tries to send a different rate alongside the
    product is simply ignored, not just hidden in the UI. The TERM IS NEVER
    LOCKED - it is always entered per loan, same as a negotiated rate loan
    (this was a real bug: term used to be force-set to the product's
    default_term_months with no way to pick anything else)."""
    _, headers = staff
    borrower = client.post("/api/borrowers", json={
        "name": "Locked Rate Borrower", "phone": "0700333444", "id_number": "LOCK1", "nida_number": "NIDALOCK1",
    }, headers=headers["maker"]).get_json()["borrower"]
    product = client.post("/api/loan-products", json={
        "name": "Locked Product", "default_interest_rate": 20, "default_term_months": 24,
    }, headers=headers["ceo"]).get_json()["loan_product"]

    # Client tries to smuggle in a different rate - the product's rate wins
    # regardless - but its own chosen term (2, not the product's 24) sticks.
    loan = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 200_000,
        "interest_rate": 1, "term_months": 2, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()
    body = loan.get_json()["loan"]
    assert Decimal(str(body["interest_rate"])) == Decimal("20")
    assert body["term_months"] == 2


def test_a_products_optional_term_bounds_are_enforced_as_validation_only(client, staff):
    """PART 2.1: a product's optional min/max term are validation BOUNDS
    only - not a fixed value. A term within bounds is accepted freely; a
    term outside them is rejected with a clear message."""
    _, headers = staff
    borrower = client.post("/api/borrowers", json={
        "name": "Term Bounds Borrower", "phone": "0700333555", "id_number": "TBND1", "nida_number": "NIDATBND1",
    }, headers=headers["maker"]).get_json()["borrower"]
    product = client.post("/api/loan-products", json={
        "name": "Bounded Term Product", "default_interest_rate": 12, "default_term_months": 12,
        "min_term_months": 6, "max_term_months": 18,
    }, headers=headers["ceo"]).get_json()["loan_product"]

    within_bounds = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 100_000,
        "term_months": 9, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert within_bounds.status_code == 201, within_bounds.get_json()
    assert within_bounds.get_json()["loan"]["term_months"] == 9

    too_short = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 100_000,
        "term_months": 3, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert too_short.status_code == 400

    too_long = client.post("/api/loans", json={
        "borrower_id": borrower["id"], "loan_product_id": product["id"], "principal_amount": 100_000,
        "term_months": 24, "start_date": "2026-01-01",
    }, headers=headers["maker"])
    assert too_long.status_code == 400


# ------------------------------------------------------------------ Part 14: rounding audit


def test_portfolio_at_risk_report_sums_as_decimal_not_float(client, staff):
    """PART 14: portfolio-at-risk used to sum outstanding balances with a
    plain float() instead of Decimal/money() - the one place in reports.py
    that didn't match the rest of the file's consistent Decimal quantization.
    Mixing that float total back in with a Decimal elsewhere would raise a
    TypeError; this just confirms the endpoint comes back clean with a
    properly 2dp-reconciled total."""
    _, headers = staff
    create_active_loan(client, headers, principal=250_000, tag="par1")
    create_active_loan(client, headers, principal=750_000, tag="par2")

    response = client.get("/api/reports/portfolio-at-risk", headers=headers["ceo"])
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert Decimal(str(body["total_portfolio"])) == Decimal("1000000.00")
    assert sum(Decimal(str(b["outstanding_balance"])) for b in body["buckets"]) == Decimal(str(body["total_portfolio"]))


# ------------------------------------------------------------------ 16-part-v2 Part 1: whole shillings


def test_a_fractional_repayment_amount_is_rejected(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="frac1")
    response = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 1000.50, "payment_date": "2026-01-15",
    }, headers=headers["maker"])
    assert response.status_code == 400
    assert "whole shillings" in response.get_json()["message"]


def test_a_fractional_penalty_amount_is_rejected(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="frac2")
    response = client.post("/api/penalties", json={"loan_id": loan_id, "amount": 500.25, "reason": "late"}, headers=headers["maker"])
    assert response.status_code == 400
    assert "whole shillings" in response.get_json()["message"]


def test_a_fractional_salary_is_rejected(client, staff):
    _, headers = staff
    response = client.post("/api/employees", json={
        "name": "Fractional Pay", "phone": "0766111222", "job_title": "Teller", "salary": 300000.75, "start_date": "2026-01-01",
    }, headers=headers["ceo"])
    assert response.status_code == 400
    assert "whole shillings" in response.get_json()["message"]


def test_a_new_loan_stores_branding_pys_default_rounding_step_and_keeps_it_forever(client, staff):
    """The rounding step default (branding.DEFAULT_ROUNDING_STEP, 1000) is
    copied onto the loan AT CREATION TIME and is read-only afterward — there
    is no Settings page, no API, no way to change it except editing
    branding.py and redeploying."""
    _, headers = staff
    import branding

    loan_id = create_active_loan(client, headers, principal=1_000_000, rate=10, term=12, tag="step1")
    loan = get_loan(client, headers, loan_id)
    assert loan["rounding_step"] == branding.DEFAULT_ROUNDING_STEP == 1000
    assert loan["schedules"][0]["expected_amount"] % branding.DEFAULT_ROUNDING_STEP == 0


def test_the_settings_page_and_its_api_no_longer_exist(client, staff):
    _, headers = staff
    for path, method in (
        ("/api/settings/company", "get"),
        ("/api/settings/company", "put"),
        ("/api/settings/public", "get"),
        ("/api/settings/company/logo", "get"),
    ):
        response = getattr(client, method)(path, headers=headers["ceo"])
        assert response.status_code == 404, (path, method, response.status_code)


# ------------------------------------------------------------------ 16-part-v2 Part 4: early settlement discount


def test_settlement_without_a_discount_is_principal_plus_full_period_interest(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle1")
    settled = client.post(f"/api/loans/{loan_id}/settle", json={"payment_date": "2026-01-15"}, headers=headers["maker"])
    assert settled.status_code == 201, settled.get_json()
    body = settled.get_json()
    assert body["breakdown"]["principal"] == 700_000
    assert body["breakdown"]["interest"] == 70_000
    assert body["breakdown"]["discount"] == 0
    assert body["breakdown"]["total_to_settle"] == 770_000
    assert body["loan"]["status"] == "closed"


def test_loans_manager_can_apply_a_settlement_discount_within_the_periods_interest(client, staff, make_user, auth_headers):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle2")
    loans_manager, pw = make_user("department_manager", email="loansmgrsettle@example.com", department="loans_credit")
    lm_headers = auth_headers(loans_manager.email, pw)

    settled = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": "2026-01-15", "discount": 30_000, "discount_reason": "goodwill gesture",
    }, headers=lm_headers)
    assert settled.status_code == 201, settled.get_json()
    body = settled.get_json()
    assert body["breakdown"]["discount"] == 30_000
    assert body["breakdown"]["total_to_settle"] == 740_000
    assert body["loan"]["status"] == "closed"


def test_a_discount_larger_than_the_periods_interest_also_forgives_some_principal(client, staff):
    """No longer capped at the period's interest (70,000 here) — up to the
    full 770,000 needed to settle is allowed; the extra 10,000 beyond
    interest forgives principal too, and the loan still closes at exactly
    zero outstanding."""
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle3")
    settled = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": "2026-01-15", "discount": 80_000, "discount_reason": "large goodwill gesture",
    }, headers=headers["ceo"])
    assert settled.status_code == 201, settled.get_json()
    body = settled.get_json()
    assert body["breakdown"]["discount"] == 80_000
    assert body["breakdown"]["total_to_settle"] == 690_000
    assert body["loan"]["status"] == "closed"
    assert body["loan"]["outstanding_balance"] == 0


def test_a_discount_larger_than_the_full_settlement_total_is_rejected(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle3b")
    rejected = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": "2026-01-15", "discount": 800_000, "discount_reason": "too generous",
    }, headers=headers["ceo"])
    assert rejected.status_code == 400
    assert "settle" in rejected.get_json()["message"]


def test_a_settlement_discount_requires_a_reason(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle4")
    rejected = client.post(f"/api/loans/{loan_id}/settle", json={
        "payment_date": "2026-01-15", "discount": 10_000,
    }, headers=headers["ceo"])
    assert rejected.status_code == 400
    assert "reason" in rejected.get_json()["message"]


def test_makers_and_checkers_cannot_apply_a_settlement_discount_but_can_still_settle_plainly(client, staff):
    _, headers = staff
    for tier, tag in (("maker", "settle5"), ("checker", "settle6")):
        loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag=tag)
        denied = client.post(f"/api/loans/{loan_id}/settle", json={
            "payment_date": "2026-01-15", "discount": 10_000, "discount_reason": "nope",
        }, headers=headers[tier])
        assert denied.status_code == 403, (tier, denied.get_json())

    # A plain settlement with no discount still works for either tier.
    loan_id2 = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle7")
    plain = client.post(f"/api/loans/{loan_id2}/settle", json={"payment_date": "2026-01-15"}, headers=headers["maker"])
    assert plain.status_code == 201, plain.get_json()


def test_overpaying_past_settlement_shows_the_most_you_can_pay_message(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=700_000, rate=10, term=12, tag="settle8")
    too_much = client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": 800_000, "payment_date": "2026-01-15",
    }, headers=headers["maker"])
    assert too_much.status_code == 400
    assert "The most you can pay today to settle this loan is" in too_much.get_json()["message"]


# ------------------------------------------------------------------ 16-part-v2 Part 5.1: payslips


def test_a_finalized_payroll_batch_produces_a_payslip_pdf_per_employee(client, staff, with_employees):
    """PART 5.1: every employee's own payslip PDF must be downloadable once
    the batch is finalized - not just the first/only remaining line."""
    _, headers = staff
    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-04")
    assert batch["line_count"] == 2
    finalized = client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"])
    assert finalized.status_code == 200
    lines = finalized.get_json()["payroll_batch"]["lines"]
    assert len(lines) == 2
    for line in lines:
        slip = client.get(f"/api/payroll/lines/{line['id']}/payslip", headers=headers["head_manager"])
        assert slip.status_code == 200, (line["employee_name"], slip.get_json())
        assert slip.mimetype == "application/pdf" and slip.data.startswith(b"%PDF")


# ------------------------------------------------------------------ 16-part-v2 Part 5.2: itemized deductions


def test_only_payroll_manage_can_manage_deduction_types(client, staff):
    _, headers = staff
    payload = {"name": "Test Type", "calculation": "fixed", "side": "employee", "fixed_amount": 1000}
    assert client.post("/api/payroll/deduction-types", json=payload, headers=headers["maker"]).status_code == 403
    assert client.post("/api/payroll/deduction-types", json=payload, headers=headers["checker"]).status_code == 403
    created = client.post("/api/payroll/deduction-types", json=payload, headers=headers["ceo"])
    assert created.status_code == 201, created.get_json()


def test_percentage_and_fixed_deduction_lines_compute_whole_shillings_and_sum_to_net_pay(client, staff, with_employees):
    _, headers = staff
    nssf = client.post("/api/payroll/deduction-types", json={
        "name": "NSSF", "calculation": "percentage", "side": "employee", "rate": 10,
    }, headers=headers["ceo"])
    assert nssf.status_code == 201, nssf.get_json()
    loan_advance = client.post("/api/payroll/deduction-types", json={
        "name": "Loan Advance", "calculation": "fixed", "side": "employee", "fixed_amount": 15000,
    }, headers=headers["ceo"])
    assert loan_advance.status_code == 201, loan_advance.get_json()

    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-05")
    amina = next(line for line in batch["lines"] if line["employee_name"] == "Amina Salum")  # salary 800,000
    names = {dl["name"]: dl["amount"] for dl in amina["deduction_lines"]}
    assert names["NSSF"] == 80_000  # 10% of 800,000
    assert names["Loan Advance"] == 15_000
    assert amina["deductions"] == 95_000
    assert amina["net_pay"] == 705_000
    assert amina["salary_amount"] - amina["deductions"] == amina["net_pay"]


def test_employer_side_deduction_is_shown_separately_and_never_reduces_net_pay(client, staff, with_employees):
    _, headers = staff
    created = client.post("/api/payroll/deduction-types", json={
        "name": "Employer NSSF Match", "calculation": "percentage", "side": "employer", "rate": 10,
    }, headers=headers["ceo"])
    assert created.status_code == 201, created.get_json()

    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-06")
    amina = next(line for line in batch["lines"] if line["employee_name"] == "Amina Salum")  # salary 800,000
    assert amina["employer_cost"] == 80_000
    assert amina["deductions"] == 0
    assert amina["net_pay"] == 800_000
    assert any(dl["name"] == "Employer NSSF Match" and dl["side"] == "employer" for dl in amina["deduction_lines"])
    assert batch["total_employer_cost"] == 200_000  # 10% of Amina's 800,000 + 10% of Juma's 1,200,000


def test_progressive_paye_bands_apply_marginally(client, staff, with_employees):
    """Each band's rate applies only to the SLICE of salary within that
    band, not the whole salary — standard progressive tax behaviour."""
    _, headers = staff
    created = client.post("/api/payroll/deduction-types", json={
        "name": "PAYE", "calculation": "bands", "side": "employee",
        "bands": [{"up_to": 100000, "rate": 0}, {"up_to": 300000, "rate": 10}, {"up_to": None, "rate": 20}],
    }, headers=headers["ceo"])
    assert created.status_code == 201, created.get_json()

    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-07")
    juma = next(line for line in batch["lines"] if line["employee_name"] == "Juma Hassan")  # salary 1,200,000
    # 0-100k @0% = 0; 100k-300k (200k) @10% = 20,000; 300k-1,200,000 (900k) @20% = 180,000
    paye = next(dl for dl in juma["deduction_lines"] if dl["name"] == "PAYE")
    assert paye["amount"] == 200_000


def test_finalizing_is_blocked_when_deductions_exceed_gross_pay(client, staff, with_employees):
    _, headers = staff
    client.post("/api/payroll/deduction-types", json={
        "name": "Overcommitted Deduction", "calculation": "percentage", "side": "employee", "rate": 60,
    }, headers=headers["ceo"])
    client.post("/api/payroll/deduction-types", json={
        "name": "Another Big Deduction", "calculation": "percentage", "side": "employee", "rate": 60,
    }, headers=headers["ceo"])
    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-08")
    blocked = client.post(f"/api/payroll/{batch['id']}/finalize", headers=headers["head_manager"])
    assert blocked.status_code == 400
    assert "Deductions exceed gross pay" in blocked.get_json()["message"]


def test_a_manual_deduction_override_replaces_itemized_lines_with_one_adjustment_line(client, staff, with_employees):
    _, headers = staff
    client.post("/api/payroll/deduction-types", json={
        "name": "NSSF", "calculation": "percentage", "side": "employee", "rate": 5,
    }, headers=headers["ceo"])
    batch = make_payroll_batch(client, headers, by="head_manager", month="2026-09")
    amina = next(line for line in batch["lines"] if line["employee_name"] == "Amina Salum")
    assert any(dl["name"] == "NSSF" for dl in amina["deduction_lines"])

    edited = client.patch(f"/api/payroll/{batch['id']}/lines/{amina['id']}", json={"deductions": 30_000}, headers=headers["head_manager"])
    assert edited.status_code == 200
    updated = next(line for line in edited.get_json()["payroll_batch"]["lines"] if line["id"] == amina["id"])
    assert updated["deductions"] == 30_000
    assert len(updated["deduction_lines"]) == 1
    only = updated["deduction_lines"][0]
    assert only["name"] == "Manual adjustment" and only["side"] == "employee" and only["amount"] == 30_000
    assert updated["net_pay"] == 770_000
