from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import func

from extensions import db
from models import AuditLog, Borrower, Expense, Loan, PaymentSchedule, Repayment, User
from routes.auth import auth_required

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def export_file(title, rows, fmt):
    if fmt == "pdf":
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        stream = BytesIO()
        pdf = canvas.Canvas(stream, pagesize=letter)
        pdf.drawString(40, 760, title)
        y = 735
        for row in rows:
            pdf.drawString(40, y, " | ".join(f"{key}: {value}" for key, value in row.items())[:110])
            y -= 16
            if y < 40:
                pdf.showPage(); y = 760
        pdf.save(); stream.seek(0)
        return send_file(stream, as_attachment=True, download_name=f"{title.lower().replace(' ', '-')}.pdf", mimetype="application/pdf")
    from openpyxl import Workbook
    workbook = Workbook(); sheet = workbook.active; sheet.title = title[:31]
    if rows:
        sheet.append(list(rows[0].keys()))
        for row in rows: sheet.append(list(row.values()))
    stream = BytesIO(); workbook.save(stream); stream.seek(0)
    return send_file(stream, as_attachment=True, download_name=f"{title.lower().replace(' ', '-')}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def overdue_days(loan, today=None):
    today = today or date.today()
    unpaid = [row for row in loan.schedules if row.status in ("upcoming", "partial", "late", "missed") and row.due_date < today]
    return (today - min(row.due_date for row in unpaid)).days if unpaid else 0


@reports_bp.get("/portfolio-at-risk")
@auth_required
def portfolio_at_risk(_user):
    buckets = {"1-30": [], "31-60": [], "61-90": [], "90+": []}
    for loan in Loan.query.filter(Loan.status.in_(["active", "approved"])).all():
        days = overdue_days(loan)
        if 1 <= days <= 30: buckets["1-30"].append(loan)
        elif 31 <= days <= 60: buckets["31-60"].append(loan)
        elif 61 <= days <= 90: buckets["61-90"].append(loan)
        elif days > 90: buckets["90+"].append(loan)
    portfolio = sum(float(loan.outstanding_balance or 0) for loan in Loan.query.filter_by(status="active").all())
    rows = []
    for name, loans in buckets.items():
        balance = sum(float(loan.outstanding_balance or 0) for loan in loans)
        rows.append({"bucket": name, "loan_count": len(loans), "outstanding_balance": balance, "portfolio_percentage": (balance / portfolio * 100) if portfolio else 0})
    if request.args.get("format") in ("pdf", "excel"): return export_file("portfolio-at-risk", rows, request.args["format"])
    return jsonify({"buckets": rows, "total_portfolio": portfolio})


@reports_bp.get("/collections")
@auth_required
def collections(_user):
    period = request.args.get("period", "daily")
    if period not in ("daily", "weekly", "monthly"): return jsonify({"message": "period must be daily, weekly, or monthly"}), 400
    grouped = defaultdict(lambda: {"expected_amount": 0, "actual_collected": 0})
    for schedule in PaymentSchedule.query.all():
        key_date = schedule.due_date
        key = key_date.isoformat() if period == "daily" else f"{key_date.isocalendar().year}-W{key_date.isocalendar().week:02d}" if period == "weekly" else key_date.strftime("%Y-%m")
        grouped[key]["expected_amount"] += float(schedule.expected_amount or 0)
    for repayment in Repayment.query.all():
        key_date = repayment.payment_date
        key = key_date.isoformat() if period == "daily" else f"{key_date.isocalendar().year}-W{key_date.isocalendar().week:02d}" if period == "weekly" else key_date.strftime("%Y-%m")
        grouped[key]["actual_collected"] += float(repayment.amount_paid or 0)
    rows = [{"period": key, **value} for key, value in sorted(grouped.items())]
    if request.args.get("format") in ("pdf", "excel"): return export_file("collections", rows, request.args["format"])
    return jsonify({"collections": rows})


@reports_bp.get("/borrower-statement/<int:borrower_id>")
@auth_required
def borrower_statement(_user, borrower_id):
    borrower = Borrower.query.get_or_404(borrower_id)
    rows = []
    for loan in borrower.loans:
        rows.append({"type": "loan", "loan_id": loan.id, "date": loan.start_date.isoformat(), "amount": float(loan.principal_amount), "status": loan.status})
        rows.extend({"type": "repayment", "loan_id": loan.id, "date": repayment.payment_date.isoformat(), "amount": float(repayment.amount_paid), "balance_after": float(repayment.balance_after)} for repayment in loan.repayments)
    if request.args.get("format") in ("pdf", "excel"): return export_file("borrower-statement", rows, request.args["format"])
    return jsonify({"borrower": {"id": borrower.id, "name": borrower.name, "email": borrower.email}, "statement": rows})


@reports_bp.get("/capital-flow")
@auth_required
def capital_flow(_user):
    start = date.fromisoformat(request.args["start_date"]) if request.args.get("start_date") else date.min
    end = date.fromisoformat(request.args["end_date"]) if request.args.get("end_date") else date.max
    rows = []
    for repayment in Repayment.query.filter(Repayment.payment_date.between(start, end)).all(): rows.append({"date": repayment.payment_date.isoformat(), "capital_in": float(repayment.amount_paid), "capital_out": 0})
    for loan in Loan.query.filter(Loan.start_date.between(start, end), Loan.status.in_(["approved", "active", "closed"])).all(): rows.append({"date": loan.start_date.isoformat(), "capital_in": 0, "capital_out": float(loan.principal_amount)})
    for expense in Expense.query.filter(Expense.date.between(start, end), Expense.status == "approved").all(): rows.append({"date": expense.date.isoformat(), "capital_in": 0, "capital_out": float(expense.amount)})
    if request.args.get("format") in ("pdf", "excel"): return export_file("capital-flow", rows, request.args["format"])
    return jsonify({"flow": rows})


@reports_bp.get("/loan-officer-performance")
@auth_required
def loan_officer_performance(_user):
    rows = []
    for officer in User.query.filter_by(role="maker").all():
        loans = Loan.query.filter_by(created_by=officer.id).all()
        good = sum(1 for loan in loans if overdue_days(loan) == 0)
        rows.append({"user_id": officer.id, "name": officer.name, "loans_created": len(loans), "total_value": sum(float(loan.principal_amount) for loan in loans), "good_standing_percentage": good / len(loans) * 100 if loans else 0, "overdue_percentage": (len(loans) - good) / len(loans) * 100 if loans else 0})
    if request.args.get("format") in ("pdf", "excel"): return export_file("loan-officer-performance", rows, request.args["format"])
    return jsonify({"officers": rows})
