from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
TWELVE = Decimal("12")


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(start_date, months):
    month = start_date.month - 1 + months
    year = start_date.year + month // 12
    month = month % 12 + 1
    day = min(start_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def amortization_schedule(principal, interest_rate, term_months, start_date=None):
    principal = money(principal)
    annual_rate = Decimal(str(interest_rate))
    term_months = int(term_months)
    if principal <= 0 or term_months <= 0 or annual_rate < 0:
        raise ValueError("principal, interest_rate, and term_months are invalid")

    monthly_rate = annual_rate / HUNDRED / TWELVE
    if monthly_rate == 0:
        payment = money(principal / term_months)
    else:
        payment = money(
            principal * monthly_rate
            / (Decimal(1) - (Decimal(1) + monthly_rate) ** (-term_months))
        )

    balance = principal
    schedule = []
    for period in range(1, term_months + 1):
        interest = money(balance * monthly_rate)
        payment_amount = money(payment)
        principal_portion = money(payment_amount - interest)
        if period == term_months or principal_portion > balance:
            principal_portion = balance
            payment_amount = money(principal_portion + interest)
        balance = money(balance - principal_portion)
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
    return schedule


def totals(schedule):
    return {
        "total_principal": money(sum((row["principal_portion"] for row in schedule), Decimal(0))),
        "total_interest": money(sum((row["interest_portion"] for row in schedule), Decimal(0))),
        "total_paid": money(sum((row["payment_amount"] for row in schedule), Decimal(0))),
    }
