"""PART 0 (baseline simulation) - this file is a REPORT, not a correctness
check (the real, asserting coverage for Phase 3's rules lives in
tests/test_phase3_repayment_rules.py): it prints exactly what
apply_repayment()/amortization_schedule() do for five partial/late-payment
scenarios, with NO changes made to make the numbers look better. The
printed output (via `pytest -s`) was originally captured into
docs/partial-payment-baseline.txt (and docs/partial-payment-after.txt)
across the earlier whole-shilling rounding rewrite, and again into
docs/phase3-repayment-before.txt / docs/phase3-repayment-after.txt across
Phase 3 (Grace's repayment rules): interest is now computed fresh from the
ACTUAL outstanding balance each period. A row only closes (status 'paid')
once a payment covers what is CURRENTLY due on it in FULL (interest, then
principal) — any underpayment, whether or not it covers interest, leaves
the row 'partial' with its own interest/principal reduced to the residual
still owed (case A and case B below are now the same shape; only how much
of the row is left outstanding differs).

Loan under test throughout: principal 1,000,000, monthly rate 10%, term 12
months, starting 2026-01-15 - the EMI for this loan is 147,000 (whole
shillings, rounded up to the default 1,000 step).
"""
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


def make_loan(client, headers, tag):
    """A fresh, independent 1,000,000 / 10% / 12-month active loan."""
    borrower = client.post("/api/borrowers", json={
        "name": f"Baseline {tag}", "phone": f"0700{tag}", "id_number": f"BL-{tag}", "nida_number": f"NIDA-BL-{tag}",
    }, headers=headers["maker"])
    assert borrower.status_code == 201, borrower.get_json()
    loan = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"],
        "principal_amount": 1_000_000, "interest_rate": 10, "term_months": 12, "start_date": "2026-01-15",
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


def pay(client, headers, loan_id, amount, payment_date):
    return client.post("/api/repayments", json={
        "loan_id": loan_id, "amount_paid": amount, "payment_date": payment_date,
    }, headers=headers["maker"])


def report(title, loan, repayment=None, note=""):
    lines = [f"\n{'=' * 78}", title, "=" * 78]
    if note:
        lines.append(note)
    if repayment is not None:
        lines.append(
            f"Repayment recorded: interest_paid={repayment['interest_portion']}, "
            f"principal_paid={repayment['principal_portion']}, balance_after={repayment['balance_after']}"
        )
    else:
        lines.append("Repayment recorded: NONE (no repayment call made)")
    rows = loan["schedules"]
    lines.append(f"\nOutstanding principal now: {loan['outstanding_balance']}")
    lines.append(f"Loan status: {loan['status']}")
    lines.append("\nSchedule rows (period, due_date, status, principal, interest, payment):")
    for i, row in enumerate(rows, start=1):
        lines.append(
            f"  row {i}: due={row['due_date']} status={row['status']} "
            f"principal={row['principal_portion']} interest={row['interest_portion']} "
            f"payment={row['expected_amount']}"
        )
    open_rows = [r for r in rows if r["status"] in ("upcoming", "partial", "missed")]
    if open_rows:
        nxt = open_rows[0]
        lines.append(
            f"\nNext/current open row: due={nxt['due_date']} status={nxt['status']} "
            f"interest={nxt['interest_portion']} principal={nxt['principal_portion']} "
            f"payment={nxt['expected_amount']} (this IS 'next month's interest' and "
            f"'the recalculated instalment for the remaining term')"
        )
    else:
        lines.append("\nNo open rows left - loan fully paid off.")
    t = loan["totals"]
    lines.append(
        f"\nTotals row: total_principal={t['total_principal']} total_interest={t['total_interest']} "
        f"total_payable={t['total_payable']} paid_to_date={t['paid_to_date']} "
        f"remaining_instalments={t['remaining_instalments']} outstanding_balance={t['outstanding_balance']}"
    )
    print("\n".join(lines))


def test_case_A_month1_pays_120000(client, staff):
    """(A) month 1 pays 120,000 - more than the 100,000 interest due, so some
    principal is paid too, but less than the full 147,000 instalment.

    The period stays open (status 'partial') since the full instalment was
    not covered — the row shows the REAL 100,000 interest / 20,000
    principal actually paid (reduced to the 27,000 residual still owed),
    and every later row is re-amortized from the real 980,000 balance."""
    _, headers = staff
    loan_id = make_loan(client, headers, "A")
    before = get_loan(client, headers, loan_id)
    resp = pay(client, headers, loan_id, 120_000, "2026-02-15")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    after = get_loan(client, headers, loan_id)
    report(
        "CASE A: month 1 pays 120,000 (stays open 'partial' - instalment not covered in full)",
        after, repayment,
        note=f"Row 1 before payment: interest={before['schedules'][0]['interest_portion']}, "
             f"principal={before['schedules'][0]['principal_portion']}, payment={before['schedules'][0]['expected_amount']}\n"
             f"Row 1 after payment: status={after['schedules'][0]['status']}, "
             f"paid_less_than_scheduled={after['schedules'][0]['paid_less_than_scheduled']}",
    )


def test_case_B_month1_pays_60000(client, staff):
    """(B) month 1 pays 60,000 - less than the 100,000 interest due. Does the
    unpaid interest (40,000) get tracked anywhere, and does it later compound
    (get multiplied by the rate again) once the balance is re-amortized?

    Like case A, this leaves the period open ('partial') - the only
    difference is how much of the row is left owing (here, interest is
    also still outstanding; in case A only principal was)."""
    _, headers = staff
    loan_id = make_loan(client, headers, "B")
    before = get_loan(client, headers, loan_id)
    resp = pay(client, headers, loan_id, 60_000, "2026-02-15")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    after = get_loan(client, headers, loan_id)
    report(
        "CASE B: month 1 pays 60,000 (does not even cover interest - stays open, unchanged by Phase 3 item 3)",
        after, repayment,
        note=f"Row 1 before payment: interest={before['schedules'][0]['interest_portion']}, "
             f"principal={before['schedules'][0]['principal_portion']}, payment={before['schedules'][0]['expected_amount']}\n"
             f"Unpaid interest after this payment = scheduled interest (100,000) - interest_paid (60,000) = 40,000.\n"
             f"Where is it recorded? Check row 1's own interest_portion below - that IS where it lives; "
             f"there is no separate 'arrears'/'unpaid interest' ledger field anywhere in the schema.",
    )
    # Second payment next month, to observe whether the 40,000 unpaid interest
    # from month 1 ever gets multiplied by the rate again (compounding) once
    # the remaining schedule is re-amortized. "The original EMI" means
    # whatever the CURRENT system's scheduled instalment actually is - read
    # from the loan itself, not a number hardcoded to one pass's rounding.
    original_emi = before["schedules"][0]["expected_amount"]
    resp2 = pay(client, headers, loan_id, original_emi, "2026-03-15")
    assert resp2.status_code == 201, resp2.get_json()
    repayment2 = resp2.get_json()["repayment"]
    after2 = get_loan(client, headers, loan_id)
    report(
        f"CASE B follow-up: next month pays the original EMI ({original_emi}) - does the earlier unpaid interest compound?",
        after2, repayment2,
        note="If this payment's interest_paid is still based on the SAME outstanding_balance as before "
             "(1,000,000, since principal_paid was 0 in month 1), compounding is NOT happening - the "
             "40,000 unpaid interest from row 1 is only ever paid down directly on row 1 itself, never "
             "folded into the principal balance or charged interest again.",
    )


def test_case_C_month1_pays_nothing_month2_pays_instalment(client, staff):
    """(C) month 1 pays nothing at all (no repayment call), then month 2
    "pays the scheduled instalment" (whatever the current system's
    scheduled instalment actually is). Which row does this actually land
    on - row 1 (still open, earliest due date) or row 2?"""
    _, headers = staff
    loan_id = make_loan(client, headers, "C")
    mid = get_loan(client, headers, loan_id)
    report(
        "CASE C, step 1: month 1 - NO payment made",
        mid, repayment=None,
        note="Expect row 1 to remain exactly as originally scheduled (status unchanged - no automatic "
             "'missed' marking happens here; that only happens via the separate daily scheduler job, "
             "which is not invoked by a repayment at all).",
    )
    instalment = mid["schedules"][1]["expected_amount"]  # "month 2's" own scheduled instalment
    resp = pay(client, headers, loan_id, instalment, "2026-03-15")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    after = get_loan(client, headers, loan_id)
    report(
        f"CASE C, step 2: month 2 pays the scheduled instalment ({instalment})",
        after, repayment,
        note="Row 1 (not row 2!) is the earliest OPEN row at this point, so apply_repayment() applies "
             "this payment against ROW 1, marking IT paid - row 2 is left untouched except for being "
             "re-amortized along with every later row on the new balance. Row 2's own due date (now in "
             "the past relative to this payment) is never checked or flagged.",
    )


def test_case_D_instalment_paid_one_day_late(client, staff):
    """(D) the full scheduled instalment paid exactly one day after the due
    date (2026-02-16 instead of 2026-02-15) - does lateness change anything
    at all in the current logic?"""
    _, headers = staff
    loan_id = make_loan(client, headers, "D")
    scheduled = get_loan(client, headers, loan_id)["schedules"][0]["expected_amount"]
    resp = pay(client, headers, loan_id, scheduled, "2026-02-16")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    after = get_loan(client, headers, loan_id)
    report(
        "CASE D: full instalment paid ONE DAY LATE (due 2026-02-15, paid 2026-02-16)",
        after, repayment,
        note="apply_repayment() never reads payment_date relative to due_date at all. Phase 3 item 1: "
             "interest IS now recomputed fresh from the loan's actual outstanding balance at the moment "
             "of payment (not read from a value fixed back at loan-creation/last-rebuild time) - but "
             "since nothing has disturbed the balance since this row was last computed, the fresh figure "
             "is numerically identical either way. Expect this to match case E (on-time). No late fee or "
             "extra interest of any kind is applied automatically for being late (that is Phase 3 item 2's "
             "separate daily-job concern, not anything a repayment itself ever does).",
    )


def test_case_E_instalment_paid_on_time_sanity_check(client, staff):
    """(E) the exact scheduled instalment paid exactly on the due date - the
    sanity-check case: this should leave the EMI for remaining rows unchanged
    (within rounding), since nothing is actually "extra" or "short" here."""
    _, headers = staff
    loan_id = make_loan(client, headers, "E")
    scheduled = get_loan(client, headers, loan_id)["schedules"][0]["expected_amount"]
    resp = pay(client, headers, loan_id, scheduled, "2026-02-15")
    assert resp.status_code == 201, resp.get_json()
    repayment = resp.get_json()["repayment"]
    after = get_loan(client, headers, loan_id)
    report(
        "CASE E (sanity check): exact scheduled instalment paid ON TIME",
        after, repayment,
        note="Expect row 1 status='paid', and row 2 onward's EMI to be unchanged (within rounding) "
             "from the original 146,763.32 - an on-time, exact payment should not move the EMI at all.",
    )
