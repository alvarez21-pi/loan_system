from datetime import date
from decimal import Decimal

from flask import Blueprint, jsonify, request

from extensions import db
from models import (
    Asset,
    Borrower,
    Employee,
    Expense,
    LeaveRequest,
    Loan,
    LoanProduct,
    PaymentSchedule,
    PayrollRun,
    Penalty,
    Repayment,
)
from routes.auth import auth_required
from services.approval import can_approve
from services.loan_calculator import amortization_schedule, money
from services.email_client import send_email

operations_bp = Blueprint("operations", __name__, url_prefix="/api")


def parse_date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be YYYY-MM-DD")


def current_user_id(user):
    return int(user.id)


def json_row(row, extra=None):
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = float(value)
        elif isinstance(value, date):
            data[key] = value.isoformat()
    if extra:
        data.update(extra)
    return data


def audit(user, action, table, record_id, details=None):
    from models import AuditLog
    db.session.add(AuditLog(user_id=user.id, action=action, table_name=table, record_id=record_id, details=details))


def error(message, status=400):
    return jsonify({"message": message}), status


def role_required(*roles):
    def decorator(fn):
        @auth_required
        def wrapped(user, *args, **kwargs):
            if user.role not in roles:
                return error("insufficient role", 403)
            return fn(user, *args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def build_schedules(loan, start_date=None, principal=None, term=None):
    rows = amortization_schedule(
        principal if principal is not None else loan.principal_amount,
        loan.interest_rate,
        term if term is not None else loan.term_months,
        start_date or loan.start_date,
    )
    loan.schedules.clear()
    for row in rows:
        loan.schedules.append(
            PaymentSchedule(
                due_date=row["due_date"],
                expected_amount=row["payment_amount"],
                principal_portion=row["principal_portion"],
                interest_portion=row["interest_portion"],
                status="upcoming",
            )
        )


@operations_bp.post("/loan-calculator/preview")
@auth_required
def calculator_preview(_user):
    data = request.get_json(silent=True) or {}
    if data.get("interest_type", "reducing_balance") != "reducing_balance":
        return error("only reducing_balance is supported")
    try:
        schedule = amortization_schedule(data["principal"], data["interest_rate"], data["term_months"])
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    for row in schedule:
        row.pop("due_date", None)
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = float(value)
    totals = {
        key: float(value)
        for key, value in {
            "total_principal": sum((Decimal(str(row["principal_portion"])) for row in schedule), Decimal(0)),
            "total_interest": sum((Decimal(str(row["interest_portion"])) for row in schedule), Decimal(0)),
            "total_paid": sum((Decimal(str(row["payment_amount"])) for row in schedule), Decimal(0)),
        }.items()
    }
    return jsonify({"schedule": schedule, "totals": totals})


@operations_bp.post("/borrowers")
@auth_required
def create_borrower(user):
    data = request.get_json(silent=True) or {}
    required = ["name", "phone", "id_number"]
    if any(not data.get(field) for field in required):
        return error("name, phone, and id_number are required")
    borrower = Borrower(
        name=data["name"].strip(), phone=data["phone"].strip(), id_number=data["id_number"].strip(),
        email=data.get("email"), address=data.get("address"), photo_url=data.get("photo_url"),
    )
    db.session.add(borrower)
    db.session.flush()
    audit(user, "CREATE", "borrowers", borrower.id)
    db.session.commit()
    return jsonify({"borrower": json_row(borrower)}), 201


@operations_bp.post("/loan-products")
@auth_required
def create_product(user):
    data = request.get_json(silent=True) or {}
    try:
        product = LoanProduct(
            name=data["name"], default_interest_rate=data["default_interest_rate"],
            min_term_months=int(data["min_term_months"]), max_term_months=int(data["max_term_months"]),
            min_amount=data["min_amount"], max_amount=data["max_amount"], is_active=True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(product)
    db.session.commit()
    return jsonify({"loan_product": json_row(product)}), 201


@operations_bp.put("/loan-products/<int:product_id>")
@auth_required
def update_product(user, product_id):
    product = LoanProduct.query.get_or_404(product_id)
    data = request.get_json(silent=True) or {}
    for field in ("name", "default_interest_rate", "min_term_months", "max_term_months", "min_amount", "max_amount", "is_active"):
        if field in data:
            setattr(product, field, data[field])
    db.session.commit()
    return jsonify({"loan_product": json_row(product)})


@operations_bp.post("/loans")
@auth_required
def create_loan(user):
    data = request.get_json(silent=True) or {}
    try:
        start_date = parse_date(data["start_date"], "start_date")
        borrower = Borrower.query.get(int(data["borrower_id"]))
        product = LoanProduct.query.get(int(data["loan_product_id"]))
        principal = money(data["principal_amount"])
        rate = Decimal(str(data["interest_rate"]))
        term = int(data["term_months"])
        if not borrower or not product:
            return error("borrower or loan product not found", 404)
        if not (product.min_amount <= principal <= product.max_amount):
            return error("principal is outside product limits")
        if not (product.min_term_months <= term <= product.max_term_months):
            return error("term is outside product limits")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    loan = Loan(
        borrower_id=borrower.id, loan_product_id=product.id, principal_amount=principal,
        interest_rate=rate, term_months=term, start_date=start_date, status="pending_approval",
        outstanding_balance=principal, created_by=user.id,
    )
    db.session.add(loan)
    db.session.flush()
    build_schedules(loan)
    audit(user, "CREATE", "loans", loan.id)
    db.session.commit()
    return jsonify({"loan": json_row(loan)}), 201


@operations_bp.post("/repayments")
@auth_required
def create_repayment(user):
    data = request.get_json(silent=True) or {}
    try:
        loan = Loan.query.get(int(data["loan_id"]))
        amount = money(data["amount_paid"])
        payment_date = parse_date(data["payment_date"], "payment_date")
        if not loan:
            return error("loan not found", 404)
        if amount <= 0 or amount > money(loan.outstanding_balance):
            return error("payment must be positive and no greater than outstanding balance")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    old_balance = money(loan.outstanding_balance)
    remaining = [s for s in sorted(loan.schedules, key=lambda row: row.due_date) if s.status in ("upcoming", "partial", "late")]
    schedule = remaining[0] if remaining else None
    scheduled_interest = money(schedule.interest_portion) if schedule else Decimal("0")
    interest_portion = min(amount, scheduled_interest)
    principal_portion = min(amount - interest_portion, old_balance)
    loan.outstanding_balance = money(old_balance - principal_portion)
    if loan.outstanding_balance == 0:
        loan.status = "closed"
    if schedule:
        schedule.status = "late" if payment_date > schedule.due_date else "paid" if amount >= schedule.expected_amount else "partial"
        if schedule.status == "partial":
            schedule.expected_amount = amount
        future = remaining[1:] if schedule.status in ("paid", "late") else remaining[1:]
        if future and loan.outstanding_balance:
            projected = amortization_schedule(loan.outstanding_balance, loan.interest_rate, len(future), payment_date)
            for entry, projection in zip(future, projected):
                entry.expected_amount = projection["payment_amount"]
                entry.principal_portion = projection["principal_portion"]
                entry.interest_portion = projection["interest_portion"]
                entry.due_date = projection["due_date"]
    repayment = Repayment(
        loan_id=loan.id, schedule_id=schedule.id if schedule else None, amount_paid=amount,
        payment_date=payment_date, principal_portion=principal_portion,
        interest_portion=interest_portion, balance_after=loan.outstanding_balance,
    )
    db.session.add(repayment)
    audit(user, "CREATE", "repayments", 0, f"loan_id={loan.id}")
    db.session.commit()
    return jsonify({"repayment": json_row(repayment)}), 201


@operations_bp.post("/penalties")
@auth_required
def create_penalty(user):
    data = request.get_json(silent=True) or {}
    loan = Loan.query.get(data.get("loan_id"))
    if not loan or not data.get("amount") or not data.get("reason"):
        return error("loan_id, amount, and reason are required")
    penalty = Penalty(loan_id=loan.id, amount=money(data["amount"]), reason=data["reason"], date_applied=date.today(), added_by=user.id, status="pending")
    db.session.add(penalty)
    db.session.commit()
    return jsonify({"penalty": json_row(penalty)}), 201


@operations_bp.post("/expenses")
@auth_required
def create_expense(user):
    data = request.get_json(silent=True) or {}
    try:
        expense = Expense(description=data["description"], category=data["category"], amount=money(data["amount"]), date=parse_date(data.get("date", data.get("expense_date")), "date"), added_by=user.id, status="pending")
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(expense)
    db.session.commit()
    return jsonify({"expense": json_row(expense)}), 201


@operations_bp.post("/employees")
@auth_required
def create_employee(_user):
    data = request.get_json(silent=True) or {}
    try:
        employee = Employee(name=data["name"], role=data["role"], salary=money(data["salary"]), phone=data["phone"], start_date=parse_date(data.get("start_date", data.get("hire_date")), "start_date"), is_active=True)
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(employee)
    db.session.commit()
    return jsonify({"employee": json_row(employee)}), 201


@operations_bp.post("/payroll")
@auth_required
def create_payroll(user):
    data = request.get_json(silent=True) or {}
    month = data.get("month", data.get("period"))
    if not month:
        return error("month is required")
    employees = Employee.query.filter_by(is_active=True).all()
    if not employees:
        return error("no active employees found")
    created = []
    for employee in employees:
        salary = money(employee.salary)
        created.append(PayrollRun(month=month, employee_id=employee.id, salary_amount=salary, deductions=Decimal("0"), net_pay=salary, created_by=user.id, status="pending"))
    db.session.add_all(created)
    db.session.commit()
    return jsonify({"payroll": [json_row(row) for row in created]}), 201


def decide_record(user, model, record_id, status, table, amount_field=None):
    record = model.query.get_or_404(record_id)
    if not can_approve(user, record): return error("maker-checker rule prevents self-approval", 403)
    if status == "rejected":
        reason = (request.get_json(silent=True) or {}).get("rejection_reason")
        if not reason: return error("rejection_reason is required")
        if hasattr(record, "rejection_reason"): record.rejection_reason = reason
    record.status = status
    if status == "approved":
        record.approved_by = user.id
        if isinstance(record, Loan):
            record.status = "active"
            if record.borrower and record.borrower.email:
                send_email("loan_approved", record.borrower.email, {"borrower_name": record.borrower.name, "loan_reference": f"Loan #{record.id}", "principal_amount": str(record.principal_amount), "interest_rate": str(record.interest_rate), "term_months": record.term_months})
            if loan.borrower and loan.borrower.email:
                send_email("payment_received", loan.borrower.email, {"borrower_name": loan.borrower.name, "loan_reference": f"Loan #{loan.id}", "amount_paid": str(amount), "balance_remaining": str(loan.outstanding_balance), "payment_date": payment_date.isoformat()})
        if isinstance(record, Penalty):
            record.loan.outstanding_balance = money(record.loan.outstanding_balance + record.amount)
    audit(user, status.upper(), table, record.id)
    db.session.commit()
    return jsonify({table.rstrip("s"): json_row(record)})


@operations_bp.post("/loans/<int:record_id>/approve")
@role_required("admin", "checker")
def approve_loan(user, record_id): return decide_record(user, Loan, record_id, "approved", "loan")


@operations_bp.post("/loans/<int:record_id>/reject")
@role_required("admin", "checker")
def reject_loan(user, record_id): return decide_record(user, Loan, record_id, "rejected", "loan")


@operations_bp.post("/expenses/<int:record_id>/approve")
@role_required("admin", "checker")
def approve_expense(user, record_id): return decide_record(user, Expense, record_id, "approved", "expense")


@operations_bp.post("/expenses/<int:record_id>/reject")
@role_required("admin", "checker")
def reject_expense(user, record_id): return decide_record(user, Expense, record_id, "rejected", "expense")


@operations_bp.post("/payroll/<int:record_id>/approve")
@role_required("admin", "checker")
def approve_payroll(user, record_id): return decide_record(user, PayrollRun, record_id, "approved", "payroll")


@operations_bp.post("/payroll/<int:record_id>/reject")
@role_required("admin", "checker")
def reject_payroll(user, record_id): return decide_record(user, PayrollRun, record_id, "rejected", "payroll")


@operations_bp.post("/penalties/<int:record_id>/approve")
@role_required("admin", "checker")
def approve_penalty(user, record_id): return decide_record(user, Penalty, record_id, "approved", "penalty")


@operations_bp.post("/penalties/<int:record_id>/reject")
@role_required("admin", "checker")
def reject_penalty(user, record_id): return decide_record(user, Penalty, record_id, "rejected", "penalty")


@operations_bp.get("/assets")
@auth_required
def list_assets(_user):
    return jsonify({"assets": [json_row(row) for row in Asset.query.filter_by(is_active=True).all()]})


@operations_bp.get("/capital/summary")
@auth_required
def capital_summary(_user):
    from sqlalchemy import func
    cash_capital = Decimal(str(__import__("os").getenv("CASH_CAPITAL", "0")))
    asset_total = db.session.query(func.coalesce(func.sum(Asset.value), 0)).filter_by(is_active=True).scalar()
    lent = db.session.query(func.coalesce(func.sum(Loan.outstanding_balance), 0)).filter(Loan.status == "active").scalar()
    collected = db.session.query(func.coalesce(func.sum(Repayment.amount_paid), 0)).scalar()
    return jsonify({"cash_capital": float(cash_capital), "total_asset_value": float(asset_total), "currently_lent_out": float(lent), "total_collected": float(collected), "available_to_lend": float(cash_capital - Decimal(str(lent)) + Decimal(str(collected)))})


@operations_bp.post("/assets")
@auth_required
def create_asset(user):
    data = request.get_json(silent=True) or {}
    try:
        asset = Asset(name=data["name"], type=data["type"], value=money(data["value"]), date_acquired=parse_date(data["date_acquired"], "date_acquired"), notes=data.get("notes"), is_active=True)
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(asset)
    db.session.commit()
    return jsonify({"asset": json_row(asset)}), 201


@operations_bp.put("/assets/<int:asset_id>")
@auth_required
def update_asset(user, asset_id):
    asset = Asset.query.get_or_404(asset_id)
    data = request.get_json(silent=True) or {}
    for field in ("name", "type", "notes"):
        if field in data:
            setattr(asset, field, data[field])
    if "value" in data: asset.value = money(data["value"])
    if "date_acquired" in data: asset.date_acquired = parse_date(data["date_acquired"], "date_acquired")
    db.session.commit()
    return jsonify({"asset": json_row(asset)})


@operations_bp.delete("/assets/<int:asset_id>")
@auth_required
def delete_asset(user, asset_id):
    asset = Asset.query.get_or_404(asset_id)
    asset.is_active = False
    db.session.commit()
    return jsonify({"message": "asset archived"})


@operations_bp.get("/leave-requests")
@auth_required
def list_leave_requests(_user):
    query = LeaveRequest.query
    if request.args.get("employee_id"): query = query.filter_by(employee_id=request.args["employee_id"])
    if request.args.get("status"): query = query.filter_by(status=request.args["status"])
    return jsonify({"leave_requests": [json_row(row) for row in query.all()]})


@operations_bp.post("/leave-requests")
@auth_required
def create_leave(user):
    data = request.get_json(silent=True) or {}
    try:
        leave = LeaveRequest(employee_id=int(data["employee_id"]), created_by=user.id, leave_type=data["leave_type"], start_date=parse_date(data["start_date"], "start_date"), end_date=parse_date(data["end_date"], "end_date"), reason=data.get("reason"), status="pending")
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(leave)
    db.session.commit()
    return jsonify({"leave_request": json_row(leave)}), 201


def decide_leave(user, leave_id, status):
    leave = LeaveRequest.query.get_or_404(leave_id)
    if not can_approve(user, leave): return error("maker-checker rule prevents self-approval", 403)
    if status == "rejected":
        reason = (request.get_json(silent=True) or {}).get("rejection_reason")
        if not reason: return error("rejection_reason is required")
        leave.rejection_reason = reason
    leave.status = status
    db.session.commit()
    return jsonify({"leave_request": json_row(leave)})


@operations_bp.post("/leave-requests/<int:leave_id>/approve")
@role_required("admin", "checker")
def approve_leave(user, leave_id): return decide_leave(user, leave_id, "approved")


@operations_bp.post("/leave-requests/<int:leave_id>/reject")
@role_required("admin", "checker")
def reject_leave(user, leave_id): return decide_leave(user, leave_id, "rejected")
