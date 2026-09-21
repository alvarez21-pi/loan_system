from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request

from models import (
    AuditLog,
    Borrower,
    Employee,
    Expense,
    Loan,
    LoanProduct,
    PayrollRun,
    Penalty,
    Repayment,
)
from routes.auth import auth_required

resources_bp = Blueprint("resources", __name__, url_prefix="/api")


def serialize(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def row_to_dict(row):
    return {
        column.name: serialize(getattr(row, column.name))
        for column in row.__table__.columns
    }


def collection(model, key):
    def handler(_current_user):
        return jsonify({key: [row_to_dict(row) for row in model.query.all()]})

    handler.__name__ = f"list_{key}"
    return auth_required(handler)


@resources_bp.get("/borrowers")
def list_borrowers():
    return collection(Borrower, "borrowers")()


@resources_bp.get("/borrowers/<int:borrower_id>")
@auth_required
def get_borrower(_current_user, borrower_id):
    borrower = Borrower.query.get_or_404(borrower_id)
    return jsonify({"borrower": row_to_dict(borrower)})


@resources_bp.get("/loan-products")
def list_loan_products():
    return collection(LoanProduct, "loan_products")()


@resources_bp.get("/loans")
@auth_required
def list_loans(_current_user):
    rows = []
    for loan in Loan.query.all():
        item = row_to_dict(loan)
        item["borrower_name"] = loan.borrower.name if loan.borrower else None
        item["product_name"] = loan.loan_product.name if loan.loan_product else None
        rows.append(item)
    return jsonify({"loans": rows})


@resources_bp.get("/repayments")
@auth_required
def list_repayments(_current_user):
    rows = []
    for repayment in Repayment.query.all():
        item = row_to_dict(repayment)
        item["borrower_name"] = (
            repayment.loan.borrower.name
            if repayment.loan and repayment.loan.borrower
            else None
        )
        rows.append(item)
    return jsonify({"repayments": rows})


@resources_bp.get("/expenses")
def list_expenses():
    return collection(Expense, "expenses")()


@resources_bp.get("/employees")
def list_employees():
    return collection(Employee, "employees")()


@resources_bp.get("/payroll")
def list_payroll():
    return collection(PayrollRun, "payroll")()


@resources_bp.get("/penalties")
@auth_required
def list_penalties(_current_user):
    query = Penalty.query
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    if request.args.get("loan_id"):
        query = query.filter_by(loan_id=request.args["loan_id"])
    return jsonify({"penalties": [row_to_dict(row) for row in query.all()]})


@resources_bp.get("/audit-logs")
@auth_required
def list_audit_logs(_current_user):
    rows = []
    for log in AuditLog.query.order_by(AuditLog.timestamp.desc()).all():
        item = row_to_dict(log)
        item["user"] = log.user.name if log.user else None
        rows.append(item)
    return jsonify({"audit_logs": rows})


@resources_bp.get("/dashboard/summary")
@auth_required
def dashboard_summary(_current_user):
    return jsonify(
        {
            "summary": {
                "borrowers": Borrower.query.count(),
                "loans": Loan.query.count(),
                "active_loans": Loan.query.filter_by(status="active").count(),
                "outstanding_balance": float(
                    sum((loan.outstanding_balance or 0) for loan in Loan.query.all())
                ),
            }
        }
    )
