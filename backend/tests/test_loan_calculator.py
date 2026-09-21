from decimal import Decimal

from services.loan_calculator import amortization_schedule, money, totals


def test_reducing_balance_hand_calculation():
    schedule = amortization_schedule("1000000", "10", 2)
    assert schedule[0]["interest_portion"] == Decimal("8333.33")
    assert schedule[0]["principal_portion"] == Decimal("497925.31")
    assert schedule[-1]["balance_after"] == Decimal("0.00")
    assert totals(schedule)["total_principal"] == Decimal("1000000.00")


def test_lower_balance_reduces_next_interest():
    original = amortization_schedule("1000000", "10", 12)
    reduced = amortization_schedule("900000", "10", 11)
    assert reduced[0]["interest_portion"] < original[1]["interest_portion"]


def test_zero_balance_has_no_future_interest():
    schedule = amortization_schedule("100", "12", 1)
    assert schedule[-1]["balance_after"] == Decimal("0.00")
    assert sum(row["principal_portion"] for row in schedule) == Decimal("100.00")


def test_decimal_rounding_stays_exact_over_many_cycles():
    schedule = amortization_schedule("1000000.01", "17.25", 360)
    assert all(isinstance(row["payment_amount"], Decimal) for row in schedule)
    assert schedule[-1]["balance_after"] == Decimal("0.00")
    assert totals(schedule)["total_principal"] == money("1000000.01")