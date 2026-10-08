"""Reports (Part 6.2/6.3/6.4): on-screen filters + KPI cards, exportable as a
branded PDF or a styled Excel workbook. Every endpoint needs reports:view;
the money-sensitive ones (income statement, cash flow, expenses by category)
additionally need reports:financial.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request

from models import (
    Borrower,
    CapitalEntry,
    Expense,
    Loan,
    LoanProduct,
    PaymentSchedule,
    PayrollBatch,
    Penalty,
    Repayment,
    User,
)
from routes.operations import permission_required
from services.excel import excel_report
from services.loan_calculator import local_today, money
from services.pdf import report_pdf

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def parse_range():
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    start_date = date.fromisoformat(start) if start else date(2000, 1, 1)
    end_date = date.fromisoformat(end) if end else date(2100, 1, 1)
    label = f"{start or 'inception'} to {end or 'today'}"
    return start_date, end_date, label


def money_str(value):
    return f"{Decimal(str(value or 0)):,.2f}"


def export(title, period, user, kpis, columns, rows, numeric_cols, totals_row=None, landscape=False):
    fmt = request.args.get("format")
    if fmt not in ("pdf", "excel"):
        return None
    if fmt == "pdf":
        stream = report_pdf(title, period, user.name, kpis, columns, rows, totals_row, landscape, numeric_cols)
        from flask import send_file
        return send_file(stream, as_attachment=True, download_name=f"{title.lower().replace(' ', '-')}.pdf", mimetype="application/pdf")
    stream = excel_report(title, period, user.name, kpis, columns, rows, numeric_cols, totals_row)
    from flask import send_file
    return send_file(stream, as_attachment=True, download_name=f"{title.lower().replace(' ', '-')}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def overdue_days(loan, today=None):
    """Phase 3 item 2: a delayed period's due_date gets pushed into the
    future (so the borrower isn't shown as newly overdue on a date that
    was only ever moved to accommodate them) — original_due_date never
    changes, so THIS is what "actually overdue" is measured against,
    regardless of how many times the live due_date has since shifted."""
    today = today or local_today()
    unpaid = [
        row for row in loan.schedules
        if row.status in ("upcoming", "partial", "late", "missed") and (row.original_due_date or row.due_date) < today
    ]
    return (today - min((row.original_due_date or row.due_date) for row in unpaid)).days if unpaid else 0


@reports_bp.get("/portfolio-at-risk")
@permission_required("reports:view")
def portfolio_at_risk(user):
    product_id = request.args.get("product_id", type=int)
    query = Loan.query.filter(Loan.status.in_(["active", "approved"]))
    if product_id:
        query = query.filter(Loan.loan_product_id == product_id)
    loans = query.all()

    buckets = {"1-30": [], "31-60": [], "61-90": [], "90+": []}
    overdue_list = []
    for loan in loans:
        days = overdue_days(loan)
        if 1 <= days <= 30: buckets["1-30"].append(loan)
        elif 31 <= days <= 60: buckets["31-60"].append(loan)
        elif 61 <= days <= 90: buckets["61-90"].append(loan)
        elif days > 90: buckets["90+"].append(loan)
        if days > 0:
            overdue_list.append((loan, days))
    overdue_list.sort(key=lambda pair: -pair[1])

    # PART 14: summed as Decimal/money(), not float - a float sum here could
    # pick up binary floating-point imprecision that money_str()'s later
    # Decimal(str(...)) would then quantize from, same inconsistency class as
    # every other monetary total in this file.
    portfolio = money(sum((Decimal(str(loan.outstanding_balance or 0)) for loan in Loan.query.filter_by(status="active").all()), Decimal("0")))
    rows = []
    for name, bucket_loans in buckets.items():
        balance = money(sum((Decimal(str(loan.outstanding_balance or 0)) for loan in bucket_loans), Decimal("0")))
        rows.append({"bucket": name, "loan_count": len(bucket_loans), "outstanding_balance": float(balance), "portfolio_percentage": round(float(balance / portfolio * 100) if portfolio else 0, 1)})

    overdue_rows = [
        [str(loan.id), loan.borrower.name if loan.borrower else "-", money_str(loan.outstanding_balance), str(days)]
        for loan, days in overdue_list
    ]
    par_30 = money(sum((Decimal(str(r["outstanding_balance"])) for r in rows if r["bucket"] != "1-30"), Decimal("0"))) if portfolio else Decimal("0")
    kpis = [
        ("Total portfolio", money_str(portfolio)),
        ("At risk (>30 days)", money_str(par_30)),
        ("PAR ratio", f"{(float(par_30 / portfolio) * 100) if portfolio else 0:.1f}%"),
        ("Overdue loans", str(len(overdue_list))),
    ]
    columns = ["Loan #", "Borrower", "Outstanding balance", "Days overdue"]
    exported = export("Portfolio at Risk", "as of " + local_today().isoformat(), user, kpis, columns, overdue_rows, numeric_cols=[2])
    if exported:
        return exported
    return jsonify({"buckets": rows, "total_portfolio": float(portfolio), "overdue_loans": [
        {"loan_id": loan.id, "borrower_name": loan.borrower.name if loan.borrower else None, "outstanding_balance": float(loan.outstanding_balance), "days_overdue": days}
        for loan, days in overdue_list
    ]})


@reports_bp.get("/collections")
@permission_required("reports:view")
def collections(user):
    period = request.args.get("period", "monthly")
    if period not in ("daily", "weekly", "monthly"): return jsonify({"message": "period must be daily, weekly, or monthly"}), 400
    start_date, end_date, label = parse_range()

    def bucket_key(key_date):
        if period == "daily": return key_date.isoformat()
        if period == "weekly": return f"{key_date.isocalendar().year}-W{key_date.isocalendar().week:02d}"
        return key_date.strftime("%Y-%m")

    grouped = defaultdict(lambda: {"expected_amount": Decimal("0"), "actual_collected": Decimal("0")})
    for schedule in PaymentSchedule.query.join(Loan).filter(PaymentSchedule.due_date.between(start_date, end_date)).all():
        grouped[bucket_key(schedule.due_date)]["expected_amount"] += Decimal(str(schedule.expected_amount or 0))
    for repayment in Repayment.query.filter(Repayment.payment_date.between(start_date, end_date)).all():
        grouped[bucket_key(repayment.payment_date)]["actual_collected"] += Decimal(str(repayment.amount_paid or 0))

    rows = []
    total_expected = total_actual = Decimal("0")
    for key in sorted(grouped):
        expected, actual = grouped[key]["expected_amount"], grouped[key]["actual_collected"]
        total_expected += expected; total_actual += actual
        efficiency = float(actual / expected * 100) if expected else 0
        rows.append([key, money_str(expected), money_str(actual), f"{efficiency:.1f}%"])
    efficiency_overall = float(total_actual / total_expected * 100) if total_expected else 0
    kpis = [("Expected", money_str(total_expected)), ("Collected", money_str(total_actual)), ("Efficiency", f"{efficiency_overall:.1f}%")]
    columns = ["Period", "Expected", "Collected", "Efficiency"]
    exported = export("Collections", label, user, kpis, columns, rows, numeric_cols=[1, 2])
    if exported:
        return exported
    return jsonify({"collections": [
        {"period": r[0], "expected_amount": float(grouped[r[0]]["expected_amount"]), "actual_collected": float(grouped[r[0]]["actual_collected"]), "efficiency_percentage": round(float(grouped[r[0]]["actual_collected"] / grouped[r[0]]["expected_amount"] * 100) if grouped[r[0]]["expected_amount"] else 0, 1)}
        for r in rows
    ], "totals": {"expected_amount": float(total_expected), "actual_collected": float(total_actual), "efficiency_percentage": round(efficiency_overall, 1)}})


@reports_bp.get("/disbursements")
@permission_required("reports:view")
def disbursements(user):
    start_date, end_date, label = parse_range()
    product_id = request.args.get("product_id", type=int)
    officer_id = request.args.get("officer_id", type=int)
    query = Loan.query.filter(Loan.status.in_(["approved", "active", "closed"]), Loan.start_date.between(start_date, end_date))
    if product_id: query = query.filter(Loan.loan_product_id == product_id)
    if officer_id: query = query.filter(Loan.created_by == officer_id)
    loans = query.order_by(Loan.start_date).all()

    rows = [[str(l.id), l.borrower.name if l.borrower else "-", l.loan_product.name if l.loan_product else "-", l.start_date.isoformat(), money_str(l.principal_amount), l.creator_name_snapshot or "-"] for l in loans]
    total = sum((Decimal(str(l.principal_amount)) for l in loans), Decimal("0"))
    kpis = [("Loans disbursed", str(len(loans))), ("Total principal", money_str(total)), ("Average loan size", money_str(total / len(loans) if loans else 0))]
    columns = ["Loan #", "Borrower", "Product", "Date", "Principal", "Officer"]
    exported = export("Disbursements", label, user, kpis, columns, rows, numeric_cols=[4], totals_row=["", "", "", "Total", money_str(total), ""])
    if exported:
        return exported
    return jsonify({"disbursements": [{"loan_id": l.id, "borrower_name": l.borrower.name if l.borrower else None, "product_name": l.loan_product.name if l.loan_product else None, "date": l.start_date.isoformat(), "principal_amount": float(l.principal_amount), "officer": l.creator_name_snapshot} for l in loans], "total_principal": float(total)})


@reports_bp.get("/income-statement")
@permission_required("reports:financial")
def income_statement(user):
    start_date, end_date, label = parse_range()
    interest_income = sum((Decimal(str(r.interest_portion)) for r in Repayment.query.filter(Repayment.payment_date.between(start_date, end_date)).all()), Decimal("0"))
    penalty_income = sum((Decimal(str(p.amount)) for p in Penalty.query.filter(Penalty.status == "approved", Penalty.date_applied.between(start_date, end_date)).all()), Decimal("0"))
    expenses_total = sum((Decimal(str(e.amount)) for e in Expense.query.filter(Expense.date.between(start_date, end_date)).all()), Decimal("0"))
    payroll_total = sum(
        (Decimal(str(line.net_pay)) for batch in PayrollBatch.query.filter_by(status="paid").all()
         if batch.finalized_at and start_date <= batch.finalized_at.date() <= end_date for line in batch.lines),
        Decimal("0"),
    )
    total_income = interest_income + penalty_income
    total_outgoings = expenses_total + payroll_total
    net = total_income - total_outgoings
    rows = [
        ["Interest income", money_str(interest_income)],
        ["Penalty income", money_str(penalty_income)],
        ["Total income", money_str(total_income)],
        ["Expenses", money_str(-expenses_total)],
        ["Payroll", money_str(-payroll_total)],
        ["Total outgoings", money_str(-total_outgoings)],
        ["Net income", money_str(net)],
    ]
    kpis = [("Total income", money_str(total_income)), ("Total outgoings", money_str(total_outgoings)), ("Net income", money_str(net))]
    columns = ["Line", "Amount"]
    exported = export("Income Statement", label, user, kpis, columns, rows, numeric_cols=[1])
    if exported:
        return exported
    return jsonify({"interest_income": float(interest_income), "penalty_income": float(penalty_income), "expenses": float(expenses_total), "payroll": float(payroll_total), "net_income": float(net)})


@reports_bp.get("/portfolio-by-product")
@permission_required("reports:view")
def portfolio_by_product(user):
    rows_out = []
    total_outstanding = Decimal("0")
    for product in LoanProduct.query.order_by(LoanProduct.name).all():
        loans = [l for l in product.loans if l.status in ("active", "closed")]
        outstanding = sum((Decimal(str(l.outstanding_balance)) for l in loans if l.status == "active"), Decimal("0"))
        principal = sum((Decimal(str(l.principal_amount)) for l in loans), Decimal("0"))
        total_outstanding += outstanding
        rows_out.append([product.name, str(len(loans)), money_str(principal), money_str(outstanding)])
    # A negotiated/custom loan (Part 4.2) has no product to group under —
    # give it its own bucket rather than silently dropping it from the report.
    negotiated = Loan.query.filter(Loan.loan_product_id.is_(None), Loan.status.in_(("active", "closed"))).all()
    if negotiated:
        n_outstanding = sum((Decimal(str(l.outstanding_balance)) for l in negotiated if l.status == "active"), Decimal("0"))
        n_principal = sum((Decimal(str(l.principal_amount)) for l in negotiated), Decimal("0"))
        total_outstanding += n_outstanding
        rows_out.append(["Negotiated (no product)", str(len(negotiated)), money_str(n_principal), money_str(n_outstanding)])
    kpis = [("Products", str(len(rows_out))), ("Total outstanding", money_str(total_outstanding))]
    columns = ["Product", "Loan count", "Total principal", "Outstanding"]
    exported = export("Portfolio by Product", "as of " + local_today().isoformat(), user, kpis, columns, rows_out, numeric_cols=[2, 3])
    if exported:
        return exported
    return jsonify({"products": [{"name": r[0], "loan_count": int(r[1]), "total_principal": r[2], "outstanding_balance": r[3]} for r in rows_out]})


@reports_bp.get("/borrower-statement/<int:borrower_id>")
@permission_required("reports:view")
def borrower_statement(user, borrower_id):
    borrower = Borrower.query.get_or_404(borrower_id)
    entries = []
    for loan in borrower.loans:
        entries.append((loan.start_date, "Loan disbursed", f"Loan #{loan.id}", Decimal(str(loan.principal_amount)), Decimal("0")))
        for repayment in loan.repayments:
            entries.append((repayment.payment_date, "Repayment", f"Loan #{loan.id}", Decimal("0"), Decimal(str(repayment.amount_paid))))
    entries.sort(key=lambda e: e[0])
    running = Decimal("0")
    rows = []
    for entry_date, kind, ref, debit, credit in entries:
        running += debit - credit
        rows.append([entry_date.isoformat(), kind, ref, money_str(debit), money_str(credit), money_str(running)])
    kpis = [("Total loans", str(len(borrower.loans))), ("Current balance owed", money_str(running))]
    columns = ["Date", "Type", "Reference", "Disbursed", "Repaid", "Running balance"]
    exported = export(f"Borrower Statement — {borrower.name}", "full history", user, kpis, columns, rows, numeric_cols=[3, 4, 5])
    if exported:
        return exported
    return jsonify({"borrower": {"id": borrower.id, "name": borrower.name, "email": borrower.email}, "statement": [
        {"date": r[0], "type": r[1], "reference": r[2], "disbursed": r[3], "repaid": r[4], "running_balance": r[5]} for r in rows
    ]})


@reports_bp.get("/cash-flow")
@permission_required("reports:financial")
def cash_flow(user):
    start_date, end_date, label = parse_range()
    rows = []
    for repayment in Repayment.query.filter(Repayment.payment_date.between(start_date, end_date)).all():
        rows.append((repayment.payment_date, "Repayment received", float(repayment.amount_paid), 0))
    for loan in Loan.query.filter(Loan.start_date.between(start_date, end_date), Loan.status.in_(["approved", "active", "closed"])).all():
        rows.append((loan.start_date, f"Loan #{loan.id} disbursed", 0, float(loan.principal_amount)))
    for expense in Expense.query.filter(Expense.date.between(start_date, end_date)).all():
        rows.append((expense.date, f"Expense: {expense.category}", 0, float(expense.amount)))
    for entry in CapitalEntry.query.filter(CapitalEntry.entry_type.in_(["injection", "withdrawal"]), CapitalEntry.date.between(start_date, end_date)).all():
        if entry.entry_type == "injection": rows.append((entry.date, "Capital injection", float(entry.amount), 0))
        else: rows.append((entry.date, "Capital withdrawal", 0, float(entry.amount)))
    rows.sort(key=lambda r: r[0])
    total_in = sum(r[2] for r in rows); total_out = sum(r[3] for r in rows)
    table_rows = [[r[0].isoformat(), r[1], money_str(r[2]), money_str(r[3])] for r in rows]
    kpis = [("Cash in", money_str(total_in)), ("Cash out", money_str(total_out)), ("Net", money_str(total_in - total_out))]
    columns = ["Date", "Description", "Cash in", "Cash out"]
    exported = export("Cash Flow", label, user, kpis, columns, table_rows, numeric_cols=[2, 3], totals_row=["", "Total", money_str(total_in), money_str(total_out)])
    if exported:
        return exported
    return jsonify({"flow": [{"date": r[0].isoformat(), "description": r[1], "cash_in": r[2], "cash_out": r[3]} for r in rows], "total_in": total_in, "total_out": total_out})


@reports_bp.get("/loan-officer-performance")
@permission_required("reports:view")
def loan_officer_performance(user):
    start_date, end_date, label = parse_range()
    rows = []
    for officer in User.query.filter_by(role="maker").all():
        loans = Loan.query.filter(Loan.created_by == officer.id, Loan.start_date.between(start_date, end_date)).all()
        good = sum(1 for loan in loans if overdue_days(loan) == 0)
        total_value = sum((Decimal(str(l.principal_amount)) for l in loans), Decimal("0"))
        rows.append([officer.name, str(len(loans)), money_str(total_value), f"{(good / len(loans) * 100) if loans else 0:.1f}%", f"{((len(loans) - good) / len(loans) * 100) if loans else 0:.1f}%"])
    kpis = [("Officers", str(len(rows))), ("Loans in period", str(sum(int(r[1]) for r in rows)))]
    columns = ["Officer", "Loans created", "Total value", "Good standing", "Overdue"]
    exported = export("Loan Officer Performance", label, user, kpis, columns, rows, numeric_cols=[2])
    if exported:
        return exported
    return jsonify({"officers": [{"name": r[0], "loans_created": int(r[1]), "total_value": r[2], "good_standing_percentage": r[3], "overdue_percentage": r[4]} for r in rows]})


@reports_bp.get("/expenses-by-category")
@permission_required("reports:financial")
def expenses_by_category(user):
    start_date, end_date, label = parse_range()
    grouped = defaultdict(lambda: Decimal("0"))
    for expense in Expense.query.filter(Expense.date.between(start_date, end_date)).all():
        grouped[expense.category] += Decimal(str(expense.amount))
    total = sum(grouped.values(), Decimal("0"))
    rows = [[category, money_str(amount), f"{(amount / total * 100) if total else 0:.1f}%"] for category, amount in sorted(grouped.items(), key=lambda kv: -kv[1])]
    kpis = [("Categories", str(len(rows))), ("Total expenses", money_str(total))]
    columns = ["Category", "Amount", "% of total"]
    exported = export("Expenses by Category", label, user, kpis, columns, rows, numeric_cols=[1], totals_row=["Total", money_str(total), "100.0%"])
    if exported:
        return exported
    return jsonify({"categories": [{"category": r[0], "amount": r[1], "percentage": r[2]} for r in rows], "total": money_str(total)})


@reports_bp.get("/payroll-summary")
@permission_required("reports:financial")
def payroll_summary(user):
    start_date, end_date, label = parse_range()
    rows = []
    total_net = Decimal("0")
    for batch in PayrollBatch.query.filter(PayrollBatch.status == "paid").order_by(PayrollBatch.month).all():
        if batch.finalized_at and not (start_date <= batch.finalized_at.date() <= end_date):
            continue
        net = sum((Decimal(str(l.net_pay)) for l in batch.lines), Decimal("0"))
        total_net += net
        rows.append([batch.month, str(len(batch.lines)), money_str(net)])
    kpis = [("Batches", str(len(rows))), ("Total paid", money_str(total_net))]
    columns = ["Month", "Employees", "Net paid"]
    exported = export("Payroll Summary", label, user, kpis, columns, rows, numeric_cols=[2])
    if exported:
        return exported
    return jsonify({"batches": [{"month": r[0], "employee_count": int(r[1]), "net_paid": r[2]} for r in rows]})


@reports_bp.get("/leave-summary")
@permission_required("reports:view")
def leave_summary(user):
    from models import LeaveRequest
    start_date, end_date, label = parse_range()
    rows = []
    grouped = defaultdict(lambda: {"pending": 0, "approved": 0, "rejected": 0})
    for leave in LeaveRequest.query.filter(LeaveRequest.start_date.between(start_date, end_date)).all():
        name = leave.employee.name if leave.employee else "Unknown"
        grouped[name][leave.status] += 1
    for name, counts in sorted(grouped.items()):
        rows.append([name, str(counts["pending"]), str(counts["approved"]), str(counts["rejected"])])
    kpis = [("Employees with leave", str(len(rows)))]
    columns = ["Employee", "Pending", "Approved", "Rejected"]
    exported = export("Leave Summary", label, user, kpis, columns, rows, numeric_cols=[])
    if exported:
        return exported
    return jsonify({"employees": [{"name": r[0], "pending": int(r[1]), "approved": int(r[2]), "rejected": int(r[3])} for r in rows]})
