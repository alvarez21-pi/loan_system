"""Two pieces of client-feedback work, as automated tests:

1. Loan edits no longer go through maker-checker (Grace's correction) — a
   loan's own terms (principal/rate/term/type) can be changed directly by
   anyone who could have created it, even once it's approved/active/has
   repayments against it. The one hard rule: a Repayment row, and any
   PaymentSchedule row that already has one against it ('paid'/'partial'),
   is NEVER altered by an edit — only the genuinely forward-looking,
   not-yet-paid remainder of the schedule is dropped and rebuilt on the
   new terms.

2. A second loan type, 'interest_only': months 1..N-1 are interest-only
   (on a principal that never reduces except via a real extra payment),
   month N is that month's interest plus the full remaining principal.
   "Fully paid" (status 'closed') fires ONLY when outstanding_balance
   reaches zero — never merely because every scheduled interest
   instalment has been paid — reusing the exact same balance-driven
   status flip apply_repayment() already used for the original loan type,
   not a second, type-specific rule.
"""
from decimal import Decimal

import pytest

from models import AuditLog


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


def make_active_loan(client, headers, tag, principal=1_200_000, rate=10, term=12, loan_type="reducing_balance", start="2026-01-15"):
    borrower = client.post("/api/borrowers", json={"name": f"Borrower {tag}", "phone": f"0700{abs(hash(tag)) % 10**6:06d}"}, headers=headers["maker"])
    assert borrower.status_code == 201, borrower.get_json()
    created = client.post("/api/loans", json={
        "borrower_id": borrower.get_json()["borrower"]["id"], "principal_amount": principal,
        "interest_rate": rate, "term_months": term, "start_date": start, "loan_type": loan_type,
    }, headers=headers["maker"])
    assert created.status_code == 201, created.get_json()
    loan_id = created.get_json()["loan"]["id"]
    approved = client.post(f"/api/loans/{loan_id}/approve", headers=headers["checker"])
    assert approved.status_code == 200, approved.get_json()
    return loan_id


def get_loan(client, headers, loan_id):
    resp = client.get(f"/api/loans/{loan_id}", headers=headers["maker"])
    assert resp.status_code == 200
    return resp.get_json()["loan"]


def open_rows(loan):
    return sorted(
        (r for r in loan["schedules"] if r["status"] in ("upcoming", "partial", "missed")),
        key=lambda r: r["due_date"],
    )


def pay(client, headers, loan_id, amount, date="2026-02-15"):
    resp = client.post("/api/repayments", json={"loan_id": loan_id, "amount_paid": amount, "payment_date": date}, headers=headers["maker"])
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


# --------------------------------------------------------------- 1. interest-only loan type

def test_interest_only_loan_runs_its_full_term_correctly(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "io1", principal=300_000, rate=10, term=3, loan_type="interest_only")
    loan = get_loan(client, headers, loan_id)
    assert loan["loan_type"] == "interest_only"
    rows = sorted(loan["schedules"], key=lambda r: r["due_date"])
    assert len(rows) == 3
    assert [Decimal(str(r["principal_portion"])) for r in rows] == [Decimal("0"), Decimal("0"), Decimal("300000")]
    assert all(Decimal(str(r["interest_portion"])) == Decimal("30000") for r in rows)

    # Month 1: exact interest-only payment — principal must NOT move, and
    # the loan must NOT show as fully paid.
    pay(client, headers, loan_id, 30_000, date="2026-02-15")
    loan = get_loan(client, headers, loan_id)
    assert loan["status"] == "active"
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("300000")

    # Month 2: same.
    pay(client, headers, loan_id, 30_000, date="2026-03-15")
    loan = get_loan(client, headers, loan_id)
    assert loan["status"] == "active"
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("300000")

    # Month 3 (final): interest + the full remaining principal — only now
    # does the loan close.
    result = pay(client, headers, loan_id, 330_000, date="2026-04-15")
    assert result["loan"]["status"] == "closed"
    assert Decimal(str(result["loan"]["outstanding_balance"])) == Decimal("0")


def test_early_extra_payment_reduces_principal_and_recalculates_without_shortening_the_term(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "io2", principal=1_200_000, rate=10, term=12, loan_type="interest_only")

    # Month 1: exact interest-only — no change to principal.
    pay(client, headers, loan_id, 120_000, date="2026-02-15")

    # Month 2: scheduled interest (120,000) PLUS a 200,000 extra paydown —
    # "the interest has to be dragged to zero first to start touching
    # principal" (the waterfall apply_repayment() already does generically),
    # and the EXCESS over interest is what reduces principal.
    pay(client, headers, loan_id, 320_000, date="2026-03-15")

    loan = get_loan(client, headers, loan_id)
    assert loan["status"] == "active"
    assert Decimal(str(loan["outstanding_balance"])) == Decimal("1000000")

    remaining = open_rows(loan)
    # Term is NOT shortened by the paydown — the loan still ends at its
    # originally scheduled final month (10 instalments left after 2 paid).
    assert len(remaining) == 10
    new_monthly_interest = Decimal("100000")  # 1,000,000 x 10%
    for row in remaining[:-1]:
        assert Decimal(str(row["interest_portion"])) == new_monthly_interest
        assert Decimal(str(row["principal_portion"])) == Decimal("0")
    final = remaining[-1]
    assert Decimal(str(final["interest_portion"])) == new_monthly_interest
    assert Decimal(str(final["principal_portion"])) == Decimal("1000000")

    # Only full settlement — not a paydown — can end the loan early.
    loan = get_loan(client, headers, loan_id)
    full_settle = pay(client, headers, loan_id, loan["settlement_amount"], date="2026-04-15")
    assert Decimal(str(full_settle["loan"]["outstanding_balance"])) == Decimal("0")
    assert full_settle["loan"]["status"] == "closed"


def test_fully_paid_never_fires_while_principal_is_still_owed(client, staff):
    """The ambiguous point in Grace's description, resolved the safe way:
    paying every scheduled interest instalment is NOT enough — the status
    only flips to 'closed' once outstanding_balance itself is zero."""
    _, headers = staff
    loan_id = make_active_loan(client, headers, "io3", principal=100_000, rate=5, term=4, loan_type="interest_only")
    for i, d in enumerate(["2026-02-15", "2026-03-15", "2026-04-15"], start=1):
        result = pay(client, headers, loan_id, 5_000, date=d)
        assert result["loan"]["status"] == "active", f"closed too early after interest-only instalment {i}"
        assert Decimal(str(result["loan"]["outstanding_balance"])) == Decimal("100000")
    final = pay(client, headers, loan_id, 105_000, date="2026-05-15")
    assert final["loan"]["status"] == "closed"


# --------------------------------------------------------------- 2. loan edit (no maker-checker)

def test_loan_edit_applies_immediately_with_no_approval_step_and_is_audited(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e1", principal=1_000_000, rate=10, term=10)
    # Only the maker's own token is used here — no checker involved at all.
    edited = client.put(f"/api/loans/{loan_id}", json={"interest_rate": 15, "term_months": 8}, headers=headers["maker"])
    assert edited.status_code == 200, edited.get_json()
    assert Decimal(str(edited.get_json()["loan"]["interest_rate"])) == Decimal("15")
    assert edited.get_json()["loan"]["term_months"] == 8

    audited = AuditLog.query.filter_by(table_name="loans", record_id=loan_id, action="EDIT").first()
    assert audited is not None
    assert "interest_rate" in audited.details and "term_months" in audited.details


def test_editing_an_active_loan_with_repayments_never_touches_past_repayments(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e2", principal=1_200_000, rate=10, term=12)
    loan = get_loan(client, headers, loan_id)
    rows_before_any_payment = open_rows(loan)
    first_row = rows_before_any_payment[0]
    second_row_due_date = rows_before_any_payment[1]["due_date"]
    instalment = Decimal(str(first_row["expected_amount"]))

    pay(client, headers, loan_id, instalment, date="2026-02-15")
    before = get_loan(client, headers, loan_id)
    paid_row_before = next(r for r in before["schedules"] if r["status"] == "paid")
    repayment_before = before["repayments"][0]

    # Edit the loan's terms post-disbursement, post-repayment.
    edited = client.put(f"/api/loans/{loan_id}", json={"interest_rate": 20, "term_months": 12}, headers=headers["maker"])
    assert edited.status_code == 200, edited.get_json()

    after = get_loan(client, headers, loan_id)
    # The Repayment record is byte-for-byte unchanged.
    repayment_after = after["repayments"][0]
    assert repayment_after == repayment_before
    # The PaymentSchedule row that repayment settled is unchanged too.
    paid_row_after = next(r for r in after["schedules"] if r["status"] == "paid")
    assert paid_row_after["principal_portion"] == paid_row_before["principal_portion"]
    assert paid_row_after["interest_portion"] == paid_row_before["interest_portion"]
    assert paid_row_after["due_date"] == paid_row_before["due_date"]

    # Only the forward remainder (11 not-yet-paid rows) was recalculated,
    # now reflecting the new 20% rate — and still landing on the ORIGINAL
    # due dates (an edit changes money, never the calendar).
    remaining = open_rows(after)
    assert len(remaining) == 11
    assert remaining[0]["due_date"] == second_row_due_date
    expected_interest = Decimal(str(after["outstanding_balance"])) * Decimal("20") / Decimal("100")
    # whole_up rounds the exact interest up — the row's own interest must be
    # at least that much and never less.
    assert Decimal(str(remaining[0]["interest_portion"])) >= expected_interest


def test_cannot_shrink_term_below_instalments_already_settled(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e3", principal=1_200_000, rate=10, term=12)
    loan = get_loan(client, headers, loan_id)
    first_row = open_rows(loan)[0]
    pay(client, headers, loan_id, Decimal(str(first_row["expected_amount"])), date="2026-02-15")

    too_short = client.put(f"/api/loans/{loan_id}", json={"term_months": 1}, headers=headers["maker"])
    assert too_short.status_code == 400
    assert "already settled" in too_short.get_json()["message"].lower()


def test_loan_type_can_be_switched_by_an_edit_and_forward_schedule_follows_the_new_type(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e4", principal=600_000, rate=10, term=6, loan_type="reducing_balance")
    edited = client.put(f"/api/loans/{loan_id}", json={"loan_type": "interest_only"}, headers=headers["maker"])
    assert edited.status_code == 200, edited.get_json()
    loan = get_loan(client, headers, loan_id)
    assert loan["loan_type"] == "interest_only"
    remaining = open_rows(loan)
    assert len(remaining) == 6
    for row in remaining[:-1]:
        assert Decimal(str(row["principal_portion"])) == Decimal("0")
    assert Decimal(str(remaining[-1]["principal_portion"])) == Decimal("600000")


def test_editing_a_closed_loan_is_rejected(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e5", principal=100_000, rate=5, term=1)
    loan = get_loan(client, headers, loan_id)
    settle = pay(client, headers, loan_id, loan["settlement_amount"], date="2026-02-15")
    assert settle["loan"]["status"] == "closed"
    blocked = client.put(f"/api/loans/{loan_id}", json={"interest_rate": 12}, headers=headers["maker"])
    assert blocked.status_code == 409


def test_a_checker_who_cannot_create_loans_also_cannot_edit_one(client, staff):
    _, headers = staff
    loan_id = make_active_loan(client, headers, "e6", principal=200_000, rate=10, term=6)
    denied = client.put(f"/api/loans/{loan_id}", json={"interest_rate": 12}, headers=headers["checker"])
    assert denied.status_code == 403
