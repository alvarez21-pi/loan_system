from calendar import monthrange
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ONE = Decimal("1")
HUNDRED = Decimal("100")
DEFAULT_ROUNDING_STEP = 1000

APP_TIMEZONE = ZoneInfo("Africa/Dar_es_Salaam")


def local_today():
    """"Today" in the business's own timezone, not the server's — the
    container runs in UTC (no TZ set), so plain date.today() shows
    YESTERDAY's date for the first 3 hours after midnight in Dar es
    Salaam (UTC+3). Every date that defaults to "today" for a loan
    start_date/payment_date/penalty date, or that the daily job compares
    a due_date against, must use this instead."""
    return datetime.now(APP_TIMEZONE).date()


def clamp_nonneg(value):
    """Never negative, and never the "-0" Decimal renders for a negative
    value that rounds to zero (Part 1.1d)."""
    value = Decimal(value)
    if value <= 0:
        return Decimal(0)
    return value


def money(value):
    """The one shared monetary quantization: a WHOLE shilling (Part 1.3 -
    every money amount in this system is a whole number), ordinary
    HALF_UP rounding, never negative. This is for generic amounts (sums,
    totals, already-whole inputs) - NOT for the loan schedule's own
    computed interest/instalment, which must only ever round UP (never
    down) so the lender is never short; those use `whole_up()`/
    `round_up_to_step()` below instead."""
    return clamp_nonneg(Decimal(str(value)).quantize(ONE, rounding=ROUND_HALF_UP))


def is_whole_shillings(value):
    """True if `value` has no fractional part at all - used to REJECT a
    fractional amount at input validation (Part 1.3), never to round it."""
    try:
        d = Decimal(str(value))
    except Exception:
        return False
    return d == d.to_integral_value()


def whole_up(value):
    """Round UP to the next whole shilling - never down, never negative
    (Part 1.1a). Used for a row's own computed interest."""
    return clamp_nonneg(Decimal(str(value)).quantize(ONE, rounding=ROUND_CEILING))


def round_up_to_step(value, step=DEFAULT_ROUNDING_STEP):
    """Round UP to the next multiple of `step` whole shillings (Part 1.1b).
    A step of 1 is just the next whole shilling. Never negative."""
    step = int(step) if step else DEFAULT_ROUNDING_STEP
    if step < 1:
        step = 1
    step = Decimal(step)
    value = clamp_nonneg(Decimal(str(value)))
    if value == 0:
        return Decimal(0)
    units = (value / step).to_integral_value(rounding=ROUND_CEILING)
    return units * step


def add_months(start_date, months):
    month = start_date.month - 1 + months
    year = start_date.year + month // 12
    month = month % 12 + 1
    day = min(start_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def amortization_schedule(principal, interest_rate, term_months, start_date=None, step=DEFAULT_ROUNDING_STEP):
    """EMI / reducing-balance schedule, in whole shillings, rounded UP only.

    interest_rate is a MONTHLY percentage (10 means 10% per month) and is used
    directly as the per-period rate: there is no division by 12 anywhere.

    Rounding (Part 1.1 - never short the lender, never charge more than the
    exact unrounded amount requires rounding up, never down):
    - Each row's interest = balance x monthly rate, rounded UP to the next
      whole shilling (`whole_up`).
    - The instalment is the EXACT (unrounded) EMI, computed once on the
      original balance/term, rounded UP to the next multiple of `step`
      (default 1,000; step=1 means "next whole shilling"). The SAME
      instalment is reused for every row (constant payment, standard EMI),
      except where it's clamped below.
    - A row's payment can never exceed that row's own remaining balance
      plus its own interest - whichever row that happens on (the natural
      final period, OR an earlier period when a small loan's balance plus
      interest no longer reaches the rounded-up instalment) closes the
      loan out exactly there, and the schedule ends at that row - it never
      continues appending trailing zero rows afterward.
    """
    principal = money(principal)
    monthly_percent = Decimal(str(interest_rate))
    term_months = int(term_months)
    if principal <= 0 or term_months <= 0 or monthly_percent < 0:
        raise ValueError("principal, interest_rate, and term_months are invalid")

    monthly_rate = monthly_percent / HUNDRED  # percent -> fraction, already per month
    if monthly_rate == 0:
        exact_emi = principal / term_months
    else:
        exact_emi = (
            principal * monthly_rate
            / (Decimal(1) - (Decimal(1) + monthly_rate) ** (-term_months))
        )
    instalment = round_up_to_step(exact_emi, step)

    balance = principal
    schedule = []
    for period in range(1, term_months + 1):
        interest = whole_up(balance * monthly_rate)
        max_payment = balance + interest  # never exceed what's actually left to settle
        payment_amount = min(instalment, max_payment)
        if period == term_months:
            # The natural last period always closes out exactly, even if
            # rounding left the instalment a shade under what's needed.
            payment_amount = max_payment
        principal_portion = clamp_nonneg(payment_amount - interest)
        balance = clamp_nonneg(balance - principal_portion)
        schedule.append(
            {
                "period": period,
                "due_date_offset_months": period,
                "due_date": add_months(start_date, period) if start_date else None,
                "principal_portion": principal_portion,
                "interest_portion": interest,
                "payment_amount": payment_amount,
                "balance_after": balance,
            }
        )
        if balance <= 0:
            # The balance cleared before the natural final period (a small
            # loan, or a chunky rounding step) - the schedule ends HERE,
            # showing the actual number of instalments it took (Part 1.1c).
            break
    return schedule


def schedule_totals(triples):
    """(principal_portion, interest_portion, payment_amount) triples -> the one
    totals computation shared by the calculator, loan-creation preview, loan
    detail page, schedule PDF and borrower statement, so those numbers can
    never drift apart (DESIGN.md — totals are always server-computed from the
    same schedule rows, never re-derived per page).

    Each column is the exact sum of its (already whole-shilling) rows (Part
    1.6) - no further rounding decision to make, since whole + whole is
    always whole.

    `monthly_payment` is the modal (most common) payment amount across the
    rows — the regular instalment, robust to the final instalment (or, on an
    actively-repaid loan, a part-paid row) differing by a rounding remainder.
    """
    triples = list(triples)
    total_principal = money(sum((Decimal(str(p)) for p, _, _ in triples), Decimal(0)))
    total_interest = money(sum((Decimal(str(i)) for _, i, _ in triples), Decimal(0)))
    total_paid = money(sum((Decimal(str(a)) for _, _, a in triples), Decimal(0)))
    if triples:
        amounts = Counter(str(money(a)) for _, _, a in triples)
        monthly_payment = money(amounts.most_common(1)[0][0])
    else:
        monthly_payment = money(0)
    return {
        "total_principal": total_principal,
        "total_interest": total_interest,
        "total_paid": total_paid,
        "total_payable": total_paid,
        "monthly_payment": monthly_payment,
        "instalment_count": len(triples),
    }


def totals(schedule):
    return schedule_totals(
        (row["principal_portion"], row["interest_portion"], row["payment_amount"]) for row in schedule
    )
