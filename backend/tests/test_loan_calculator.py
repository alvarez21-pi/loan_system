from decimal import Decimal

from services.loan_calculator import (
    amortization_schedule,
    money,
    round_up_to_step,
    totals,
    whole_up,
)


def test_reducing_balance_hand_calculation():
    # Updated for Part 1: whole shillings, instalment rounded UP to the
    # default 1,000 step (was 576190.48/476190.48 in cents - no longer valid).
    schedule = amortization_schedule("1000000", "10", 2)
    assert schedule[0]["interest_portion"] == Decimal("100000")
    assert schedule[0]["payment_amount"] == Decimal("577000")
    assert schedule[0]["principal_portion"] == Decimal("477000")
    assert schedule[-1]["balance_after"] == Decimal("0")
    assert totals(schedule)["total_principal"] == Decimal("1000000")


def test_lower_balance_reduces_next_interest():
    original = amortization_schedule("1000000", "10", 12)
    reduced = amortization_schedule("900000", "10", 11)
    assert reduced[0]["interest_portion"] < original[1]["interest_portion"]


def test_zero_balance_has_no_future_interest():
    schedule = amortization_schedule("100", "12", 1)
    assert schedule[-1]["balance_after"] == Decimal("0")
    assert sum(row["principal_portion"] for row in schedule) == Decimal("100")


def test_decimal_rounding_stays_exact_over_many_cycles():
    # 1,000,000.01 principal snaps to a whole 1,000,000 shilling (Part 1.3);
    # the 17.25% rate over 360 months with the default 1,000 step pays the
    # loan off in far fewer than 360 instalments (each one rounds up a lot
    # relative to the balance) - the schedule correctly ends early rather
    # than appending 360 rows.
    schedule = amortization_schedule("1000000.01", "17.25", 360)
    assert all(isinstance(row["payment_amount"], Decimal) for row in schedule)
    assert len(schedule) < 360
    assert schedule[-1]["balance_after"] == Decimal("0")
    assert totals(schedule)["total_principal"] == Decimal("1000000")


def test_monthly_rate_10_percent_reference_case():
    # 1,000,000 at 10% PER MONTH over 12 months; the rate is never divided by
    # 12. Whole-shilling, rounded-up-to-1,000 reference values (Part 1.7).
    schedule = amortization_schedule("1000000", "10", 12)
    assert schedule[0]["payment_amount"] == Decimal("147000")
    assert schedule[0]["principal_portion"] == Decimal("47000")
    assert schedule[0]["interest_portion"] == Decimal("100000")
    assert schedule[-1]["payment_amount"] == Decimal("141944")
    assert schedule[-1]["balance_after"] == Decimal("0")
    assert totals(schedule)["total_interest"] == Decimal("758944")
    assert totals(schedule)["total_paid"] == Decimal("1758944")


def test_monthly_rate_15_percent_reference_case():
    schedule = amortization_schedule("1000000", "15", 12)
    assert schedule[0]["payment_amount"] == Decimal("185000")
    assert schedule[0]["interest_portion"] == Decimal("150000")
    assert schedule[-1]["payment_amount"] == Decimal("169950")
    assert schedule[-1]["balance_after"] == Decimal("0")
    assert totals(schedule)["total_interest"] == Decimal("1204950")
    assert totals(schedule)["total_paid"] == Decimal("2204950")


def test_zero_rate_splits_principal_evenly_with_step_of_one():
    # With the default 1,000 step a 1,200 loan would pay off in 2 chunky
    # rows - pass step=1 to get the original "evenly split" intent back.
    schedule = amortization_schedule("1200", "0", 12, step=1)
    assert all(row["interest_portion"] == Decimal("0") for row in schedule)
    assert schedule[0]["payment_amount"] == Decimal("100")
    assert len(schedule) == 12


# ------------------------------------------------------------------ Part 1: whole shillings, rounded up


def test_interest_is_never_rounded_down():
    # balance * rate here is 333333.33...; it must round UP to 333334, never
    # down to 333333 (that would be a cent the lender is short, now a whole
    # shilling short).
    assert whole_up(Decimal("333333.33")) == Decimal("333334")
    assert whole_up(Decimal("333333.00")) == Decimal("333333")  # exact stays exact


def test_round_up_to_step_defaults_to_1000_and_a_step_of_1_is_next_shilling():
    assert round_up_to_step(Decimal("146763.32"), 1000) == Decimal("147000")
    assert round_up_to_step(Decimal("146763.32"), 1) == Decimal("146764")
    assert round_up_to_step(Decimal("147000"), 1000) == Decimal("147000")  # exact multiple stays put


def test_money_never_shows_negative_zero():
    assert money(Decimal("-0.3")) == Decimal("0")
    assert str(money(Decimal("-0.3"))) == "0"
    assert money(Decimal("-5")) == Decimal("0")


def test_principal_always_sums_exactly_to_the_loan_amount():
    for principal, rate, term in [(1_000_000, 10, 12), (1_000_000, 15, 12), (500, 10, 3), (100, 12, 1), (1, 25, 6)]:
        schedule = amortization_schedule(principal, rate, term)
        assert sum(row["principal_portion"] for row in schedule) == money(principal)


def test_final_balance_is_always_exactly_zero():
    for principal, rate, term in [(1_000_000, 10, 12), (750_000, 22, 6), (1, 1, 1)]:
        schedule = amortization_schedule(principal, rate, term)
        assert schedule[-1]["balance_after"] == Decimal("0")


def test_no_row_or_total_is_ever_negative_or_fractional_even_for_very_small_loans():
    for principal, rate, term, step in [(1, 50, 24, 1000), (2, 100, 36, 1), (5, 0, 10, 1000)]:
        schedule = amortization_schedule(principal, rate, term, step=step)
        for row in schedule:
            for key in ("principal_portion", "interest_portion", "payment_amount", "balance_after"):
                value = row[key]
                assert value >= 0, (principal, rate, term, key, value)
                assert value == value.to_integral_value(), (principal, rate, term, key, value)
        t = totals(schedule)
        for key in ("total_principal", "total_interest", "total_paid"):
            assert t[key] >= 0 and t[key] == t[key].to_integral_value()


def test_client_is_never_charged_less_than_the_exact_unrounded_amount():
    # The instalment is the exact EMI rounded UP - it can never be below the
    # true, unrounded EMI (that would undercharge and leave the lender short).
    exact = (
        Decimal("1000000") * Decimal("0.10")
        / (Decimal(1) - Decimal("1.10") ** Decimal(-12))
    )
    schedule = amortization_schedule("1000000", "10", 12)
    assert schedule[0]["payment_amount"] >= exact
    # And each row's interest is never below balance * rate exactly.
    assert schedule[0]["interest_portion"] >= Decimal("1000000") * Decimal("0.10")


def test_totals_equal_the_sum_of_the_rows_after_a_recalculation():
    # Simulate a mid-term recalculation: re-amortize on a smaller balance
    # and over fewer periods, using the loan's own stored step.
    remaining = amortization_schedule("953000", "10", 11, step=1000)
    t = totals(remaining)
    assert t["total_principal"] == sum(row["principal_portion"] for row in remaining)
    assert t["total_interest"] == sum(row["interest_portion"] for row in remaining)
    assert t["total_paid"] == sum(row["payment_amount"] for row in remaining)


def test_a_small_loan_whose_balance_clears_early_ends_the_schedule_at_that_row():
    # 500 at 10% over 3 months, default step 1,000: the first instalment
    # alone (rounded up to 1,000, clamped to balance+interest) pays it off
    # completely - the schedule must end at row 1, not pad out to 3 rows.
    schedule = amortization_schedule("500", "10", 3, step=1000)
    assert len(schedule) == 1
    assert schedule[0]["balance_after"] == Decimal("0")
