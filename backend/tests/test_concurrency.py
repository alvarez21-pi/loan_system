"""Phase 2 item 4: two concurrent requests deciding/finalizing/paying the
SAME record must never both apply. Production (Postgres) gets this primarily
from the SELECT ... FOR UPDATE added to each locked query in
routes/operations.py and routes/payroll.py: the second transaction's locked
SELECT blocks until the first commits, then re-reads the now-decided row.

SQLite (this test suite's database) does not implement row-level locking —
SQLAlchemy silently drops the FOR UPDATE clause for it — so a test running
on SQLite cannot prove the BLOCKING behaviour. What it CAN prove, and what
these tests prove, is the second, database-agnostic half of the fix: each
protected model carries an optimistic `lock_version` column
(`__mapper_args__ = {"version_id_col": ...}`), so SQLAlchemy stamps a
`WHERE lock_version = <current>` on every UPDATE and raises StaleDataError
if another transaction already changed the row. That guarantee holds
identically on SQLite and Postgres, so "a second concurrent request never
applies twice" is true everywhere, while SELECT ... FOR UPDATE additionally
makes it the cheaper, non-retrying outcome on Postgres specifically.

Each test forces the worst-case interleave (both requests read the row
before either commits) by rendezvousing two real threads at a
threading.Barrier placed right before db.session.commit() — audit() is the
last call every protected path makes before committing, so patching it is a
reliable, non-invasive synchronization point that exercises the real view
functions and the real ORM, not a hand-rolled simulation of them.
"""
import threading
from decimal import Decimal

import pytest


def race_requests(audit_owner, call_a, call_b):
    """Run call_a() and call_b() on separate threads, forcing both to reach
    the commit point (via audit()) before either actually commits."""
    barrier = threading.Barrier(2, timeout=5)
    original_audit = audit_owner.audit

    def synced_audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return result

    audit_owner.audit = synced_audit
    outcomes = {}

    def run(key, call):
        try:
            outcomes[key] = call()
        except BaseException as exc:  # surface it in the main thread instead of a bare KeyError
            outcomes[key] = exc

    t_a = threading.Thread(target=run, args=("a", call_a))
    t_b = threading.Thread(target=run, args=("b", call_b))
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)
    audit_owner.audit = original_audit
    for key in ("a", "b"):
        if isinstance(outcomes.get(key), BaseException):
            raise outcomes[key]
    return outcomes["a"], outcomes["b"]


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {
        "ceo": make_user("ceo"),
        "head_manager": make_user("head_manager"),
        "maker": make_user("maker"),
        "checker": make_user("checker"),
    }
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def create_pending_loan(client, headers, principal=500_000, rate=10, term=6, start="2026-01-01", tag="a"):
    """A loan created but NOT YET approved — left pending_approval."""
    borrower = client.post("/api/borrowers", json={
        "name": f"Race Borrower {tag}", "phone": f"07000{tag:0>5}"[:13], "id_number": f"RACE-{tag}",
    }, headers=headers["maker"])
    assert borrower.status_code == 201, borrower.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"],
        "principal_amount": principal, "interest_rate": rate, "term_months": term, "start_date": start,
    }, headers=headers["maker"])
    assert loan.status_code == 201, loan.get_json()
    return loan.get_json()["loan"]["id"]


def create_active_loan(client, headers, principal=1_000_000, rate=10, term=6, start="2026-01-01", tag="a"):
    loan_id = create_pending_loan(client, headers, principal, rate, term, start, tag)
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()
    return loan_id


def get_loan(client, headers, loan_id):
    response = client.get(f"/api/loans/{loan_id}", headers=headers["maker"])
    assert response.status_code == 200, response.get_json()
    return response.get_json()["loan"]


def test_concurrent_loan_approval_applies_only_once(client, staff):
    _, headers = staff
    loan_id = create_pending_loan(client, headers, tag="1")

    import routes.operations as ops
    outcome_a, outcome_b = race_requests(
        ops,
        lambda: client.post(f"/api/loans/{loan_id}/approve", headers=headers["ceo"]),
        lambda: client.post(f"/api/loans/{loan_id}/approve", headers=headers["head_manager"]),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [200, 409], (outcome_a.get_json(), outcome_b.get_json())
    conflict = outcome_a if outcome_a.status_code == 409 else outcome_b
    assert conflict.get_json().get("already_handled") is True

    final = get_loan(client, headers, loan_id)
    assert final["status"] == "active"


def test_concurrent_loan_approve_and_reject_only_one_applies(client, staff):
    _, headers = staff
    loan_id = create_pending_loan(client, headers, tag="2")

    import routes.operations as ops
    outcome_a, outcome_b = race_requests(
        ops,
        lambda: client.post(f"/api/loans/{loan_id}/approve", headers=headers["ceo"]),
        lambda: client.post(
            f"/api/loans/{loan_id}/reject", json={"rejection_reason": "duplicate"}, headers=headers["head_manager"]
        ),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [200, 409], (outcome_a.get_json(), outcome_b.get_json())

    final = get_loan(client, headers, loan_id)
    assert final["status"] in ("active", "rejected")
    # Whichever won is reflected consistently — not half-applied.
    winner = outcome_a if outcome_a.status_code == 200 else outcome_b
    assert final["status"] == winner.get_json()["loan"]["status"]


def test_concurrent_leave_decision_applies_only_once(client, staff):
    _, headers = staff
    employee = client.post("/api/employees", json={
        "name": "Leave Racer", "phone": "0700333444", "job_title": "Officer",
        "salary": 300000, "start_date": "2026-01-01",
    }, headers=headers["ceo"])
    assert employee.status_code == 201, employee.get_json()
    leave = client.post("/api/leave-requests", json={
        "employee_id": employee.get_json()["employee"]["id"], "leave_type": "Annual",
        "start_date": "2026-06-01", "end_date": "2026-06-03",
    }, headers=headers["ceo"])
    assert leave.status_code == 201, leave.get_json()
    leave_id = leave.get_json()["leave_request"]["id"]

    import routes.operations as ops
    outcome_a, outcome_b = race_requests(
        ops,
        lambda: client.post(f"/api/leave-requests/{leave_id}/approve", headers=headers["ceo"]),
        lambda: client.post(f"/api/leave-requests/{leave_id}/approve", headers=headers["head_manager"]),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [200, 409], (outcome_a.get_json(), outcome_b.get_json())
    conflict = outcome_a if outcome_a.status_code == 409 else outcome_b
    assert conflict.get_json().get("already_handled") is True


def test_concurrent_penalty_reversal_applies_only_once(client, staff, make_user, auth_headers):
    _, headers = staff
    loan_id = create_active_loan(client, headers, tag="pen-race")
    original_balance = Decimal(str(get_loan(client, headers, loan_id)["outstanding_balance"]))

    dept_manager, dept_pw = make_user("department_manager", department="loans_credit")
    dept_headers = auth_headers(dept_manager.email, dept_pw)

    penalty = client.post("/api/penalties", json={
        "loan_id": loan_id, "amount": 20000, "reason": "late",
    }, headers=headers["maker"])
    assert penalty.status_code == 201, penalty.get_json()
    penalty_id = penalty.get_json()["penalty"]["id"]
    # Approved by a THIRD account — neither of the two reversers below — so
    # the "original approver can't reverse their own decision" rule doesn't
    # interfere with this test.
    approved = client.post(f"/api/penalties/{penalty_id}/approve", headers=dept_headers)
    assert approved.status_code == 200, approved.get_json()

    import routes.operations as ops
    outcome_a, outcome_b = race_requests(
        ops,
        lambda: client.post(f"/api/penalties/{penalty_id}/reverse", json={"reason": "mistake A"}, headers=headers["ceo"]),
        lambda: client.post(
            f"/api/penalties/{penalty_id}/reverse", json={"reason": "mistake B"}, headers=headers["head_manager"]
        ),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [200, 409], (outcome_a.get_json(), outcome_b.get_json())

    final_balance = Decimal(str(get_loan(client, headers, loan_id)["outstanding_balance"]))
    # Exactly one reversal applied: the +20000 penalty is undone once, not twice.
    assert final_balance == original_balance


def test_concurrent_repayments_never_lose_an_update(client, staff):
    _, headers = staff
    loan_id = create_active_loan(client, headers, principal=1_000_000, tag="repay-race")
    loan = get_loan(client, headers, loan_id)
    due_date = loan["schedules"][0]["due_date"]

    # Both amounts comfortably exceed the first period's interest (~100,000
    # at 10%/month on 1,000,000), so BOTH genuinely change
    # outstanding_balance to a different value — not just re-set it to the
    # same figure — which is what actually marks the Loan row dirty and
    # exercises the lock_version conflict this test is proving.
    import routes.operations as ops
    outcome_a, outcome_b = race_requests(
        ops,
        lambda: client.post(
            "/api/repayments", json={"loan_id": loan_id, "amount_paid": 400000, "payment_date": due_date},
            headers=headers["maker"],
        ),
        lambda: client.post(
            "/api/repayments", json={"loan_id": loan_id, "amount_paid": 300000, "payment_date": due_date},
            headers=headers["checker"],
        ),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [201, 409], (outcome_a.get_json(), outcome_b.get_json())
    conflict = outcome_a if outcome_a.status_code == 409 else outcome_b
    assert conflict.get_json().get("retry") is True

    winner = outcome_a if outcome_a.status_code == 201 else outcome_b
    final_loan = get_loan(client, headers, loan_id)
    # The DB's final state matches exactly what the winning response reported
    # — the loser's computation (based on the same pre-race balance) never
    # landed on top of it.
    assert final_loan["outstanding_balance"] == winner.get_json()["loan"]["outstanding_balance"]


def test_concurrent_payroll_finalize_applies_only_once(client, staff):
    _, headers = staff
    employee = client.post("/api/employees", json={
        "name": "Payroll Racer", "phone": "0700555666", "job_title": "Officer",
        "salary": 500000, "start_date": "2026-01-01",
    }, headers=headers["ceo"])
    assert employee.status_code == 201, employee.get_json()
    batch = client.post("/api/payroll", json={"month": "2026-09"}, headers=headers["ceo"])
    assert batch.status_code == 201, batch.get_json()
    batch_id = batch.get_json()["payroll_batch"]["id"]

    import routes.payroll as payroll_module
    outcome_a, outcome_b = race_requests(
        payroll_module,
        lambda: client.post(f"/api/payroll/{batch_id}/finalize", headers=headers["ceo"]),
        lambda: client.post(f"/api/payroll/{batch_id}/finalize", headers=headers["head_manager"]),
    )
    statuses = sorted([outcome_a.status_code, outcome_b.status_code])
    assert statuses == [200, 409], (outcome_a.get_json(), outcome_b.get_json())

    final = client.get(f"/api/payroll/{batch_id}", headers=headers["ceo"]).get_json()["payroll_batch"]
    assert final["status"] == "paid"
