"""Phase 3 — Grace's repayment rules and schedule display.

Item 1: interest each period = monthly rate x the ACTUAL outstanding
principal at the start of that period, and a payment that covers interest
but leaves principal unpaid closes the period immediately (status 'paid',
flagged paid_less_than_scheduled) instead of staying open. Every remaining
period is then re-amortized by the same calculator function.

Item 2: a period counts as missed only when its due date has passed with
NO payment at all against it. Nothing about the money changes — every
unpaid due date (the missed one and every open one after it) just moves
one month later. original_due_date/delayed_months preserve the true
lateness for reporting.

Item 3: a payment smaller than the interest due keeps the OLD behaviour
(unchanged, a client decision pending) — proven here by a direct,
unmodified regression check.

Item 4: a row settled by more than one payment shows the TOTAL real
principal/interest/payment received across every payment applied to it,
not just the last one.
"""
from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {"ceo": make_user("ceo"), "maker": make_user("maker"), "checker": make_user("checker")}
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


def make_loan(client, headers, principal=1_000_000, rate=10, term=12, start="2026-01-15", tag="a"):
    borrower = client.post("/api/borrowers", json={
        "name": f"Grace Borrower {tag}", "phone": f"0700{tag}", "id_number": f"GR-{tag}",
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


def pay(client, headers, loan_id, amount, payment_date, key):
    return client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": amount, "payment_date": payment_date, "idempotency_key": key,
    }, headers=headers["maker"])


def open_rows(loan):
    return [r for r in loan["schedules"] if r["status"] in ("upcoming", "partial", "missed")]


# --------------------------------------------------------------------- item 1

def test_scenario_A_topup_before_due_date_closes_paid_schedule_unchanged(client, staff):
    """Reference loan: 1,000,000 / 10% / 12 months, step 1000, started
    2026-10-08 (first instalment due 2026-11-08, 147,000). Month 1 pays
    120,000, then the remaining 27,000 is paid BEFORE the due date — the
    row simply completes: 'Paid', balance 953,000, schedule otherwise as
    if it had been paid in full on day one (month-2 interest 95,300)."""
    _, headers = staff
    loan_id = make_loan(client, headers, start="2026-10-08", tag="A")

    first = pay(client, headers, loan_id, 120_000, "2026-10-20", "phase3-A-m1")
    assert first.status_code == 201, first.get_json()
    assert Decimal(str(first.get_json()["repayment"]["interest_portion"])) == Decimal("100000")
    assert Decimal(str(first.get_json()["repayment"]["principal_portion"])) == Decimal("20000")

    mid = get_loan(client, headers, loan_id)
    row1_mid = mid["schedules"][0]
    assert row1_mid["status"] == "partial"
    assert Decimal(str(row1_mid["original_expected_amount"])) == Decimal("147000")
    assert Decimal(str(row1_mid["paid_interest"])) == Decimal("100000")
    assert Decimal(str(row1_mid["paid_principal"])) == Decimal("20000")

    topup = pay(client, headers, loan_id, 27_000, "2026-11-01", "phase3-A-topup")  # before the 11-08 due date
    assert topup.status_code == 201, topup.get_json()

    loan = get_loan(client, headers, loan_id)
    row1 = loan["schedules"][0]
    assert row1["status"] == "paid"
    assert row1["paid_less_than_scheduled"] is False
    assert Decimal(str(row1["interest_portion"])) == Decimal("100000")
    assert Decimal(str(row1["principal_portion"])) == Decimal("47000")
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("953000")
    assert Decimal(str(loan["schedules"][1]["interest_portion"])) == Decimal("95300")

    total_interest = sum(Decimal(str(r["interest_portion"])) for r in loan["repayments"])
    assert total_interest == Decimal("100000")  # nothing extra charged by splitting the payment in two


def test_scenario_B_due_date_passes_unpaid_carries_over_and_reamortizes(client, staff):
    """Same reference loan. This time the 27,000 shortfall is NEVER paid —
    once the 2026-11-08 due date passes, the daily job carries the row
    over: locked in at the 100,000/20,000 actually received ('Partially
    paid'), and the remaining 980,000 re-amortized over 11 months exactly
    as the old, pre-regression numbers (month-2 interest 98,000,
    instalment 151,000, final 148,851, total interest 778,851). Running
    the job again for the same date changes nothing."""
    _, headers = staff
    loan_id = make_loan(client, headers, start="2026-10-08", tag="B")

    resp = pay(client, headers, loan_id, 120_000, "2026-10-20", "phase3-B-m1")
    assert resp.status_code == 201, resp.get_json()
    loan = get_loan(client, headers, loan_id)
    assert loan["schedules"][0]["status"] == "partial"
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("980000")

    from datetime import date

    from extensions import db
    from models import Loan as LoanModel
    from routes.operations import carry_over_overdue_partial_periods

    with client.application.app_context():
        loan_row = LoanModel.query.get(loan_id)
        carry_over_overdue_partial_periods(loan_row, date(2026, 11, 9))  # one day after the due date
        db.session.commit()
        # Idempotent: running it again for the same date moves nothing further.
        before_second = [(s.id, s.status, str(s.due_date), str(s.expected_amount)) for s in loan_row.schedules]
        carry_over_overdue_partial_periods(loan_row, date(2026, 11, 9))
        db.session.commit()
        after_second = [(s.id, s.status, str(s.due_date), str(s.expected_amount)) for s in loan_row.schedules]
        assert before_second == after_second

    loan = get_loan(client, headers, loan_id)
    row1 = loan["schedules"][0]
    assert row1["status"] == "paid"
    assert row1["paid_less_than_scheduled"] is True
    assert Decimal(str(row1["interest_portion"])) == Decimal("100000")
    assert Decimal(str(row1["principal_portion"])) == Decimal("20000")
    assert Decimal(str(row1["original_expected_amount"])) == Decimal("147000")
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("980000")

    row2 = loan["schedules"][1]
    assert Decimal(str(row2["interest_portion"])) == Decimal("98000")
    assert Decimal(str(row2["expected_amount"])) == Decimal("151000")
    assert Decimal(str(loan["schedules"][-1]["expected_amount"])) == Decimal("148851")
    assert loan["totals"]["total_interest"] == 778851

    # Print Scenario B as a table, exactly as asked for.
    print("\nScenario B — carried over at 2026-11-09 (one day after the 11-08 due date):")
    print(f"{'#':>2}  {'due_date':<12} {'principal':>10} {'interest':>10} {'payment':>10} {'status'}")
    for i, row in enumerate(loan["schedules"], start=1):
        print(f"{i:>2}  {row['due_date']:<12} {row['principal_portion']:>10,.0f} {row['interest_portion']:>10,.0f} {row['expected_amount']:>10,.0f} {row['status']}")
    print(f"Total interest: {loan['totals']['total_interest']:,.0f}")


def test_a_full_instalment_payment_is_labeled_paid_not_partially_paid(client, staff):
    """Paying the full 147,000 instalment in one go leaves the row plainly
    'Paid' (paid_less_than_scheduled False) and the rest of the schedule
    unaffected — no carry-over, nothing to project."""
    _, headers = staff
    loan_id = make_loan(client, headers, start="2026-10-08", tag="full")

    resp = pay(client, headers, loan_id, 147_000, "2026-10-20", "phase3-full-m1")
    assert resp.status_code == 201, resp.get_json()

    loan = get_loan(client, headers, loan_id)
    row1 = loan["schedules"][0]
    assert row1["status"] == "paid"
    assert row1["paid_less_than_scheduled"] is False
    assert Decimal(str(row1["interest_portion"])) == Decimal("100000")
    assert Decimal(str(row1["principal_portion"])) == Decimal("47000")
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("953000")
    row2 = loan["schedules"][1]
    assert Decimal(str(row2["interest_portion"])) == Decimal("95300")


def test_interest_is_recomputed_fresh_from_balance_after_a_penalty(client, staff):
    """Item 1's "actual outstanding principal" rule also closes the gap
    where a penalty directly bumps outstanding_balance without going
    through apply_repayment()/rebuilding the schedule. Approving the
    penalty resyncs the current open row's interest right away
    (resync_open_row_interest()), rather than leaving it stale until the
    next payment happens to recompute it — so a repayment afterwards
    reflects the real (post-penalty) balance, not a stale stored value."""
    _, headers = staff
    loan_id = make_loan(client, headers, tag="i2")
    penalty = client.post("/api/penalties", json={
        "loan_id": loan_id, "amount": 50_000, "reason": "late fee",
    }, headers=headers["maker"])
    assert penalty.status_code == 201, penalty.get_json()
    approved = client.post(f"/api/penalties/{penalty.get_json()['penalty']['id']}/approve", headers=headers["ceo"])
    assert approved.status_code == 200, approved.get_json()

    loan = get_loan(client, headers, loan_id)
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("1050000")
    # Resynced immediately on penalty approval: 1,050,000 x 10% = 105,000
    # — not the stale 100,000 the row was created with.
    assert Decimal(str(loan["schedules"][0]["interest_portion"])) == Decimal("105000")

    resp = pay(client, headers, loan_id, 200_000, "2026-02-15", "phase3-i2-m1")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    assert Decimal(str(repayment["interest_portion"])) == Decimal("105000")
    assert Decimal(str(repayment["principal_portion"])) == Decimal("95000")


def test_interest_is_resynced_after_a_penalty_reversal_too(client, staff, make_user, auth_headers):
    """Symmetric case: reversing a penalty lowers outstanding_balance back
    down, and the open row's interest must come back down with it."""
    _, headers = staff
    loan_id = make_loan(client, headers, tag="i2b")
    dept_manager, dept_pw = make_user("department_manager", department="loans_credit")
    dept_headers = auth_headers(dept_manager.email, dept_pw)

    penalty = client.post("/api/penalties", json={
        "loan_id": loan_id, "amount": 50_000, "reason": "late fee",
    }, headers=headers["maker"])
    assert penalty.status_code == 201, penalty.get_json()
    penalty_id = penalty.get_json()["penalty"]["id"]
    approved = client.post(f"/api/penalties/{penalty_id}/approve", headers=dept_headers)
    assert approved.status_code == 200, approved.get_json()
    assert Decimal(str(get_loan(client, headers, loan_id)["schedules"][0]["interest_portion"])) == Decimal("105000")

    reversed_resp = client.post(f"/api/penalties/{penalty_id}/reverse", json={"reason": "mistake"}, headers=headers["ceo"])
    assert reversed_resp.status_code == 200, reversed_resp.get_json()
    loan = get_loan(client, headers, loan_id)
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("1000000")
    assert Decimal(str(loan["schedules"][0]["interest_portion"])) == Decimal("100000")


# --------------------------------------------------------------------- item 2

def test_missed_period_delays_the_whole_schedule_by_one_month_unchanged_money(client, staff):
    """The exact worked example: month 1 missed -> every due date +1
    month, balance and total interest both unchanged."""
    from routes.operations import delay_missed_schedule_periods
    from models import Loan as LoanModel

    _, headers = staff
    loan_id = make_loan(client, headers, tag="d1")
    before = get_loan(client, headers, loan_id)
    original_due_dates = [row["due_date"] for row in before["schedules"]]
    original_total_interest = before["totals"]["total_interest"]

    with client.application.app_context():
        loan = LoanModel.query.get(loan_id)
        shifted = delay_missed_schedule_periods(loan, today=date(2026, 2, 16))
        assert len(shifted) == 12
        from extensions import db
        db.session.commit()

    after = get_loan(client, headers, loan_id)
    new_due_dates = [row["due_date"] for row in after["schedules"]]
    for old, new in zip(original_due_dates, new_due_dates):
        old_d, new_d = date.fromisoformat(old), date.fromisoformat(new)
        assert new_d.year * 12 + new_d.month == old_d.year * 12 + old_d.month + 1

    assert Decimal(str(after["outstanding_balance"])) == Decimal("1000000")
    assert after["totals"]["total_interest"] == original_total_interest == 758944
    for row in after["schedules"]:
        assert row["delayed_months"] == 1
        assert row["original_due_date"] in original_due_dates
        assert row["status"] == "upcoming"


def test_delay_function_is_idempotent_within_the_same_day(client, staff):
    from routes.operations import delay_missed_schedule_periods
    from models import Loan as LoanModel
    from extensions import db

    _, headers = staff
    loan_id = make_loan(client, headers, tag="d2")

    with client.application.app_context():
        loan = LoanModel.query.get(loan_id)
        first = delay_missed_schedule_periods(loan, today=date(2026, 2, 16))
        db.session.commit()
        assert len(first) == 12

        loan = LoanModel.query.get(loan_id)
        second = delay_missed_schedule_periods(loan, today=date(2026, 2, 16))
        db.session.commit()
        assert second == []  # running it again the same day shifts nothing more

        loan = LoanModel.query.get(loan_id)
        assert all(row.delayed_months == 1 for row in loan.schedules)


def test_overdue_days_uses_original_due_date_not_the_shifted_one(client, staff):
    from routes.operations import delay_missed_schedule_periods
    from models import Loan as LoanModel
    from routes.reports import overdue_days
    from extensions import db

    _, headers = staff
    loan_id = make_loan(client, headers, tag="d3")

    with client.application.app_context():
        loan = LoanModel.query.get(loan_id)
        delay_missed_schedule_periods(loan, today=date(2026, 2, 16))
        db.session.commit()
        loan = LoanModel.query.get(loan_id)
        # The live due_date is now in the future (pushed to 2026-03-15),
        # but the loan is still genuinely 1 day behind the ORIGINAL plan.
        days = overdue_days(loan, today=date(2026, 2, 16))
        assert days == 1


# --------------------------------------------------------------------- item 3

def test_payment_smaller_than_interest_due_keeps_the_existing_behaviour(client, staff):
    """Explicitly unchanged per item 3 (a client decision, not made here):
    the row stays open ('partial'), reduced by what was actually paid."""
    _, headers = staff
    loan_id = make_loan(client, headers, tag="i3")
    resp = pay(client, headers, loan_id, 60_000, "2026-02-15", "phase3-i3-under")
    assert resp.status_code == 201, resp.get_json()
    loan = get_loan(client, headers, loan_id)
    row1 = loan["schedules"][0]
    assert row1["status"] == "partial"
    assert Decimal(str(row1["interest_portion"])) == Decimal("40000")  # 100,000 - 60,000 paid
    assert Decimal(str(row1["principal_portion"])) == Decimal("47000")  # untouched
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("1000000")  # untouched


# --------------------------------------------------------------------- item 4

def test_a_row_paid_in_several_parts_shows_cumulative_totals(client, staff):
    """A row that received TWO payments (first too small to cover
    interest, second finishing it off) must show the combined real
    principal/interest/payment across BOTH — not just the second one."""
    _, headers = staff
    loan_id = make_loan(client, headers, tag="i4")

    first = pay(client, headers, loan_id, 60_000, "2026-02-15", "phase3-i4-a")
    assert first.status_code == 201, first.get_json()
    second = pay(client, headers, loan_id, 200_000, "2026-02-20", "phase3-i4-b")
    assert second.status_code == 201, second.get_json()

    loan = get_loan(client, headers, loan_id)
    row1 = loan["schedules"][0]
    assert row1["status"] == "paid"
    # interest: 40,000 remaining after the first payment, covered by the second.
    assert Decimal(str(row1["interest_portion"])) == Decimal("100000")
    # principal: 0 from the first payment + whatever the second payment left after its own interest share.
    assert Decimal(str(row1["principal_portion"])) == Decimal("160000")
    # expected_amount is the row's cumulative "payment received" = principal + interest.
    assert Decimal(str(row1["expected_amount"])) == Decimal(str(row1["interest_portion"])) + Decimal(str(row1["principal_portion"]))
    assert Decimal(str(row1["expected_amount"])) == Decimal("260000")
