from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request

from models import (
    AuditLog,
    Borrower,
    Expense,
    Loan,
    LoanProduct,
    Penalty,
    Repayment,
)
from routes.auth import auth_required
from routes.operations import OPEN_SCHEDULE_STATUSES, borrower_json, can_decide, settlement_amount
from services.listing import paginate
from services.loan_calculator import money, schedule_totals
from services.permissions import has_permission

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


@resources_bp.get("/borrowers")
@auth_required
def list_borrowers(_current_user):
    # Phase 5: search/sort/pagination is opt-in (see services/listing.py) —
    # callers that don't pass page/page_size (every OTHER page that uses
    # this same endpoint as a full borrower picker — reports, the loan
    # form, etc.) keep getting the complete, unpaginated list exactly as
    # before.
    rows, pagination = paginate(
        Borrower.query,
        request.args,
        searchable=(Borrower.name, Borrower.phone, Borrower.id_number),
        sortable={"name": Borrower.name, "phone": Borrower.phone, "created_at": Borrower.created_at},
        default_sort=Borrower.name,
    )
    body = {"borrowers": [borrower_json(row) for row in rows]}
    if pagination is not None:
        body["pagination"] = pagination
    return jsonify(body)


@resources_bp.get("/borrowers/<int:borrower_id>")
@auth_required
def get_borrower(_current_user, borrower_id):
    borrower = Borrower.query.get_or_404(borrower_id)
    return jsonify({"borrower": borrower_json(borrower)})


@resources_bp.get("/loan-products")
@auth_required
def list_loan_products(_current_user):
    return jsonify({"loan_products": [row_to_dict(row) for row in LoanProduct.query.order_by(LoanProduct.name).all()]})


def loan_summary(loan, viewer):
    """Loan row with human-readable names and whether the viewer may decide on it."""
    item = row_to_dict(loan)
    item["borrower_name"] = loan.borrower.name if loan.borrower else None
    item["product_name"] = loan.loan_product.name if loan.loan_product else None
    item["can_decide"] = can_decide(viewer, loan)
    item["settlement_amount"] = float(settlement_amount(loan))
    return item


@resources_bp.get("/loans")
@auth_required
def list_loans(current_user):
    query = Loan.query.join(Borrower)
    status_filter = request.args.get("status")
    if status_filter:
        query = query.filter(Loan.status == status_filter)
    rows, pagination = paginate(
        query,
        request.args,
        searchable=(Borrower.name, Borrower.phone),
        sortable={"id": Loan.id, "status": Loan.status, "start_date": Loan.start_date, "borrower_name": Borrower.name},
        default_sort=Loan.id.desc(),
    )
    body = {"loans": [loan_summary(loan, current_user) for loan in rows]}
    if pagination is not None:
        body["pagination"] = pagination
    return jsonify(body)


@resources_bp.get("/loans/<int:loan_id>")
@auth_required
def get_loan(current_user, loan_id):
    loan = Loan.query.get_or_404(loan_id)
    item = loan_summary(loan, current_user)
    item["borrower"] = borrower_json(loan.borrower) if loan.borrower else None
    schedule_rows = sorted(loan.schedules, key=lambda row: row.due_date)
    schedule_dicts = []
    for row in schedule_rows:
        row_dict = row_to_dict(row)
        # Cumulative real interest/principal paid against THIS row so far —
        # for a 'partial' row this differs from the row's own (residual)
        # interest_portion/principal_portion, which the UI needs to show
        # "paid 120,000 of 147,000" without guessing it from the residual.
        paid = [(Decimal(str(r.interest_portion)), Decimal(str(r.principal_portion))) for r in loan.repayments if r.schedule_id == row.id]
        row_dict["paid_interest"] = float(sum((p[0] for p in paid), Decimal("0")))
        row_dict["paid_principal"] = float(sum((p[1] for p in paid), Decimal("0")))
        schedule_dicts.append(row_dict)
    item["schedules"] = schedule_dicts
    item["repayments"] = [row_to_dict(row) for row in sorted(loan.repayments, key=lambda row: (row.payment_date, row.id))]
    item["penalties"] = [row_to_dict(row) for row in loan.penalties]
    # Totals come from the schedule rows exactly as they sit right now — paid
    # rows the way they settled, remaining rows as last re-amortized — never
    # the original at-creation plan (Part: totals reflect the current schedule).
    totals = {
        key: (float(value) if isinstance(value, Decimal) else value)
        for key, value in schedule_totals(
            (row.principal_portion, row.interest_portion, row.expected_amount) for row in schedule_rows
        ).items()
    }
    totals["paid_to_date"] = float(money(sum((Decimal(str(r.amount_paid)) for r in loan.repayments), Decimal("0"))))
    totals["outstanding_balance"] = float(loan.outstanding_balance)
    totals["remaining_instalments"] = sum(1 for row in schedule_rows if row.status in OPEN_SCHEDULE_STATUSES)
    item["totals"] = totals
    return jsonify({"loan": item})


@resources_bp.get("/repayments")
@auth_required
def list_repayments(_current_user):
    query = Repayment.query.join(Loan).join(Borrower)
    results, pagination = paginate(
        query,
        request.args,
        searchable=(Borrower.name, Borrower.phone),
        sortable={
            "id": Repayment.id, "payment_date": Repayment.payment_date,
            "amount_paid": Repayment.amount_paid, "borrower_name": Borrower.name,
        },
        default_sort=Repayment.id.desc(),
    )
    rows = []
    for repayment in results:
        item = row_to_dict(repayment)
        item["borrower_name"] = (
            repayment.loan.borrower.name
            if repayment.loan and repayment.loan.borrower
            else None
        )
        rows.append(item)
    body = {"repayments": rows}
    if pagination is not None:
        body["pagination"] = pagination
    return jsonify(body)


@resources_bp.get("/expenses")
@auth_required
def list_expenses(current_user):
    rows = []
    for expense in Expense.query.order_by(Expense.id.desc()).all():
        item = row_to_dict(expense)
        item["created_by_name"] = expense.added_by_name_snapshot
        rows.append(item)
    return jsonify({"expenses": rows})


@resources_bp.get("/penalties")
@auth_required
def list_penalties(current_user):
    query = Penalty.query
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    if request.args.get("loan_id"):
        query = query.filter_by(loan_id=request.args["loan_id"])
    rows = []
    for penalty in query.order_by(Penalty.id.desc()).all():
        item = row_to_dict(penalty)
        item["borrower_name"] = penalty.loan.borrower.name if penalty.loan and penalty.loan.borrower else None
        item["created_by_name"] = penalty.added_by_name_snapshot
        item["can_decide"] = can_decide(current_user, penalty)
        # Reversal: an approved penalty, by anyone with penalties:approve except its approver.
        item["can_reverse"] = (
            penalty.status == "approved"
            and penalty.approved_by != current_user.id
            and has_permission(current_user, "penalties:approve")
        )
        rows.append(item)
    return jsonify({"penalties": rows})


@resources_bp.get("/audit-logs/actions")
@auth_required
def list_audit_log_actions(current_user):
    """Every distinct action value ever recorded — for the audit log's action
    filter (Phase 5). Computed over the whole table, never just the current
    page, so the dropdown's options don't change as you page through."""
    if not has_permission(current_user, "audit:view"):
        return jsonify({"message": "You don't have permission to do this."}), 403
    rows = AuditLog.query.with_entities(AuditLog.action).distinct().order_by(AuditLog.action).all()
    return jsonify({"actions": [row[0] for row in rows]})


@resources_bp.get("/audit-logs")
@auth_required
def list_audit_logs(current_user):
    # The audit trail is management-only: CEO and manager have full access;
    # everyone else, even a checker with other broad permissions, has none.
    if not has_permission(current_user, "audit:view"):
        return jsonify({"message": "You don't have permission to do this."}), 403
    query = AuditLog.query
    action = (request.args.get("action") or "").strip()
    if action:
        query = query.filter(AuditLog.action == action)
    results, pagination = paginate(
        query,
        request.args,
        searchable=(AuditLog.actor_name_snapshot, AuditLog.actor_email_snapshot, AuditLog.action, AuditLog.table_name),
        sortable={"timestamp": AuditLog.timestamp, "action": AuditLog.action, "table_name": AuditLog.table_name},
        default_sort=AuditLog.timestamp.desc(),
    )
    rows = []
    for log in results:
        item = row_to_dict(log)
        item["user"] = log.actor_display_name
        rows.append(item)
    body = {"audit_logs": rows}
    if pagination is not None:
        body["pagination"] = pagination
    return jsonify(body)


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
