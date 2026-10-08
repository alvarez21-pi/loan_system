"""Payroll as a whole-batch workflow, single action (Part 1.5 / 6).

Anyone with payroll:manage prepares a batch (one line per active employee),
can preview/edit/remove lines while it is a draft, then finalizes it —
marking it paid — in one action. There is no second-person approval; the
person who prepares the batch may also be the one who finalizes it.
Payslips exist once the batch is paid.
"""
import base64
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy.orm.exc import StaleDataError

from extensions import db
from models import DeductionType, Employee, EmployeeDeduction, PayrollBatch, PayrollDeductionLine, PayrollRun
from routes.auth import auth_required
from routes.operations import (
    audit,
    error,
    json_row,
    parse_money,
    permission_required,
)
from services.email_client import send_email
from services.loan_calculator import money, whole_up
from services.permissions import has_permission
from services.pdf import payslip_pdf

payroll_bp = Blueprint("payroll", __name__, url_prefix="/api/payroll")

import re
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------- deduction types (Part 5.2)

def deduction_type_json(row):
    return json_row(row)


@payroll_bp.get("/deduction-types")
@permission_required("payroll:manage")
def list_deduction_types(user):
    rows = DeductionType.query.order_by(DeductionType.name).all()
    return jsonify({"deduction_types": [deduction_type_json(r) for r in rows]})


def parse_deduction_type_fields(data, current=None):
    calculation = data.get("calculation", current.calculation if current else "fixed")
    if calculation not in ("fixed", "percentage", "bands"):
        raise ValueError("calculation must be fixed, percentage, or bands")
    side = data.get("side", current.side if current else "employee")
    if side not in ("employee", "employer"):
        raise ValueError("side must be employee or employer")
    fields = {"calculation": calculation, "side": side, "rate": None, "fixed_amount": None, "bands": None}
    if calculation == "fixed":
        fields["fixed_amount"] = parse_money(data.get("fixed_amount", current.fixed_amount if current else 0), "fixed_amount")
    elif calculation == "percentage":
        try:
            rate = Decimal(str(data.get("rate", current.rate if current else 0)))
        except Exception:
            raise ValueError("rate must be a valid number")
        if rate < 0 or rate > 100:
            raise ValueError("rate must be between 0 and 100")
        fields["rate"] = rate
    else:  # bands — a progressive scale (e.g. PAYE), applied marginally
        bands = data.get("bands", current.bands if current else [])
        if not isinstance(bands, list):
            raise ValueError("bands must be a list of {up_to, rate}")
        for band in bands:
            if "rate" not in band:
                raise ValueError("each band needs a rate")
            if Decimal(str(band["rate"])) < 0:
                raise ValueError("a band's rate must not be negative")
        fields["bands"] = bands
    return fields


@payroll_bp.post("/deduction-types")
@permission_required("payroll:manage")
def create_deduction_type(user):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return error("name is required")
    try:
        fields = parse_deduction_type_fields(data)
    except ValueError as exc:
        return error(str(exc))
    scope = data.get("scope", "standard")
    if scope not in ("standard", "individual"):
        return error("scope must be standard or individual")
    row = DeductionType(name=name, is_active=data.get("is_active", True), scope=scope, **fields)
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error("a deduction type with this name already exists", 409)
    audit(user, "CREATE", "deduction_types", row.id, name)
    return jsonify({"deduction_type": deduction_type_json(row)}), 201


@payroll_bp.put("/deduction-types/<int:type_id>")
@permission_required("payroll:manage")
def update_deduction_type(user, type_id):
    row = DeductionType.query.get_or_404(type_id)
    data = request.get_json(silent=True) or {}
    try:
        fields = parse_deduction_type_fields(data, current=row)
    except ValueError as exc:
        return error(str(exc))
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    for key, value in fields.items():
        setattr(row, key, value)
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    if "scope" in data:
        if data["scope"] not in ("standard", "individual"):
            return error("scope must be standard or individual")
        row.scope = data["scope"]
    audit(user, "UPDATE", "deduction_types", row.id, row.name)
    db.session.commit()
    return jsonify({"deduction_type": deduction_type_json(row)})


# ---------------------------------------------------- individual employee deductions (Part 5.2 ext)

def employee_deduction_json(row):
    data = json_row(row)
    data["employee_name"] = row.employee.name if row.employee else None
    data["deduction_type_name"] = row.deduction_type.name if row.deduction_type else None
    return data


@payroll_bp.get("/employee-deductions")
@permission_required("payroll:manage")
def list_employee_deductions(user):
    query = EmployeeDeduction.query
    employee_id = request.args.get("employee_id", type=int)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    rows = query.order_by(EmployeeDeduction.id.desc()).all()
    return jsonify({"employee_deductions": [employee_deduction_json(r) for r in rows]})


def parse_employee_deduction_fields(data, current=None):
    """Fixed-vs-percentage, chosen per assignment. Returns a dict of fields
    to apply, or raises ValueError with a message for error()."""
    calculation = data.get("calculation", current.calculation if current else "fixed")
    if calculation not in ("fixed", "percentage"):
        raise ValueError("calculation must be fixed or percentage")
    fields = {"calculation": calculation, "amount": None, "rate": None}
    if calculation == "fixed":
        fields["amount"] = parse_money(data.get("amount", current.amount if current else None), "amount")
    else:
        try:
            rate = Decimal(str(data.get("rate", current.rate if current else 0)))
        except Exception:
            raise ValueError("rate must be a valid number")
        if rate < 0 or rate > 100:
            raise ValueError("rate must be between 0 and 100")
        fields["rate"] = rate
    start_month = data.get("start_month", current.start_month if current else None)
    if not isinstance(start_month, str) or not MONTH.match(start_month):
        raise ValueError("start_month is required (YYYY-MM)")
    fields["start_month"] = start_month
    end_month = data.get("end_month", current.end_month if current else None) or None
    if end_month and not MONTH.match(end_month):
        raise ValueError("end_month must be YYYY-MM")
    fields["end_month"] = end_month
    remaining_balance = data.get("remaining_balance", current.remaining_balance if current else None)
    if remaining_balance not in (None, ""):
        fields["remaining_balance"] = parse_money(remaining_balance, "remaining_balance")
    else:
        fields["remaining_balance"] = None
    return fields


@payroll_bp.post("/employee-deductions")
@permission_required("payroll:manage")
def create_employee_deduction(user):
    data = request.get_json(silent=True) or {}
    employee = Employee.query.get(data.get("employee_id"))
    if employee is None:
        return error("employee_id is required and must be a real employee")
    dtype = DeductionType.query.filter_by(id=data.get("deduction_type_id"), scope="individual").first()
    if dtype is None:
        return error("deduction_type_id must be an individual-scope deduction type")
    try:
        fields = parse_employee_deduction_fields(data)
    except ValueError as exc:
        return error(str(exc))
    row = EmployeeDeduction(employee_id=employee.id, deduction_type_id=dtype.id, **fields)
    db.session.add(row)
    db.session.flush()
    value = f"{fields['rate']}%" if fields["calculation"] == "percentage" else fields["amount"]
    audit(user, "CREATE", "employee_deductions", row.id, f"{employee.name}: {dtype.name} {value}")
    db.session.commit()
    return jsonify({"employee_deduction": employee_deduction_json(row)}), 201


@payroll_bp.put("/employee-deductions/<int:row_id>")
@permission_required("payroll:manage")
def update_employee_deduction(user, row_id):
    row = EmployeeDeduction.query.get_or_404(row_id)
    data = request.get_json(silent=True) or {}
    try:
        fields = parse_employee_deduction_fields(data, current=row)
    except ValueError as exc:
        return error(str(exc))
    for key, value in fields.items():
        setattr(row, key, value)
    audit(user, "UPDATE", "employee_deductions", row.id, f"{row.employee.name if row.employee else row.employee_id}")
    db.session.commit()
    return jsonify({"employee_deduction": employee_deduction_json(row)})


@payroll_bp.delete("/employee-deductions/<int:row_id>")
@permission_required("payroll:manage")
def remove_employee_deduction(user, row_id):
    row = EmployeeDeduction.query.get_or_404(row_id)
    row.is_active = False
    audit(user, "DEACTIVATE", "employee_deductions", row.id, f"{row.employee.name if row.employee else row.employee_id}")
    db.session.commit()
    return jsonify({"employee_deduction": employee_deduction_json(row)})


def compute_deduction_amount(dtype, gross):
    """Whole-shilling amount for one employee's gross salary (Part 1.4 -
    rounded to a whole shilling, since this is a COMPUTED figure, never a
    direct entry)."""
    gross = money(gross)
    if dtype.calculation == "fixed":
        return money(dtype.fixed_amount or 0)
    if dtype.calculation == "percentage":
        rate = Decimal(str(dtype.rate or 0))
        return whole_up(gross * rate / Decimal(100))
    if dtype.calculation == "bands":
        total = Decimal(0)
        lower = Decimal(0)
        for band in (dtype.bands or []):
            rate = Decimal(str(band.get("rate", 0)))
            upper = band.get("up_to")
            upper = Decimal(str(upper)) if upper is not None else None
            top = gross if upper is None else min(gross, upper)
            slice_amount = top - lower
            if slice_amount > 0:
                total += slice_amount * rate / Decimal(100)
            if upper is None or gross <= upper:
                break
            lower = upper
        return money(total)
    return Decimal(0)


def build_deduction_lines(gross, employee=None, month=None):
    """Every ACTIVE standard-scope deduction type's line for one employee's
    gross salary (unchanged — this is the whole-company default, e.g.
    NSSF, that every employee gets; an overcommitted standard setup is
    still allowed to exceed gross here, so finalize_batch()'s own "deductions
    exceed gross pay" guard stays meaningful), PLUS that one employee's own
    individual-scope assignments due this month (loan repayment, salary
    advance...). An individual line is capped at `available` — what's left
    of gross after standard deductions and any earlier individual lines —
    so one employee's own extra deductions can never themselves push their
    pay negative; a percentage is rounded UP, same convention as every
    other computed money figure, and balance-tracked lines separately cap
    at whatever remaining_balance is left."""
    gross = money(gross)
    lines = []
    for dtype in DeductionType.query.filter_by(is_active=True, scope="standard").order_by(DeductionType.name).all():
        amount = compute_deduction_amount(dtype, gross)
        lines.append(PayrollDeductionLine(deduction_type_id=dtype.id, name_snapshot=dtype.name, side=dtype.side, amount=amount))
    standard_employee_total = money(sum((dl.amount for dl in lines if dl.side == "employee"), Decimal(0)))
    available = max(gross - standard_employee_total, Decimal(0))
    if employee is not None and month:
        for assignment in EmployeeDeduction.query.filter_by(employee_id=employee.id, is_active=True).all():
            if assignment.start_month > month:
                continue
            if assignment.end_month and assignment.end_month < month:
                continue
            if assignment.remaining_balance is not None and money(assignment.remaining_balance) <= 0:
                continue
            if assignment.calculation == "percentage":
                amount = whole_up(gross * Decimal(str(assignment.rate or 0)) / Decimal(100))
            else:
                amount = money(assignment.amount or 0)
            if assignment.remaining_balance is not None:
                amount = min(amount, money(assignment.remaining_balance))
            dtype = assignment.deduction_type
            if dtype.side == "employee":
                amount = max(min(amount, available), Decimal(0))
                available = money(available - amount)
            lines.append(PayrollDeductionLine(
                deduction_type_id=dtype.id, employee_deduction_id=assignment.id,
                name_snapshot=dtype.name, side=dtype.side, amount=amount,
            ))
    return lines


def line_json(line):
    employee = line.employee
    data = json_row(line)
    data["employee_name"] = employee.name if employee else None
    data["job_title"] = employee.job_title if employee else None
    # Itemized deductions (Part 5.2): each line shown separately, split by
    # side - employee-side lines are what's actually subtracted to reach
    # net_pay; employer-side lines are a cost to the company, shown here too
    # but never subtracted from net pay.
    def dl_json(dl):
        row = {
            "id": dl.id, "name": dl.name_snapshot, "side": dl.side, "amount": float(dl.amount),
            "scope": "individual" if dl.employee_deduction_id else "standard",
            "is_adjusted": dl.is_adjusted,
        }
        if dl.employee_deduction_id:
            assignment = EmployeeDeduction.query.get(dl.employee_deduction_id)
            if assignment is not None and assignment.remaining_balance is not None:
                row["remaining_after"] = float(money(max(money(assignment.remaining_balance) - money(dl.amount), Decimal(0))))
        return row

    data["deduction_lines"] = [dl_json(dl) for dl in line.deduction_lines]
    return data


def batch_json(batch):
    data = json_row(batch)
    lines = [line_json(line) for line in batch.lines]
    data["lines"] = lines
    data["line_count"] = len(lines)
    data["total_gross"] = float(sum((Decimal(str(line["salary_amount"])) for line in lines), Decimal("0")))
    data["total_net"] = float(sum((Decimal(str(line["net_pay"])) for line in lines), Decimal("0")))
    data["total_employer_cost"] = float(sum((Decimal(str(line["employer_cost"])) for line in lines), Decimal("0")))
    data["creator_name"] = batch.creator_name_snapshot
    data["finalizer_name"] = batch.finalizer_name_snapshot
    data["can_finalize"] = batch.status == "draft"
    return data


@payroll_bp.get("")
@permission_required("payroll:manage")
def list_batches(user):
    batches = PayrollBatch.query.order_by(PayrollBatch.id.desc()).all()
    return jsonify({"payroll": [batch_json(batch) for batch in batches]})


@payroll_bp.get("/<int:batch_id>")
@permission_required("payroll:manage")
def get_batch(user, batch_id):
    return jsonify({"payroll_batch": batch_json(PayrollBatch.query.get_or_404(batch_id))})


@payroll_bp.post("")
@permission_required("payroll:manage")
def create_batch(user):
    data = request.get_json(silent=True) or {}
    month = data.get("month", data.get("period"))
    if not isinstance(month, str) or not MONTH.match(month):
        return error("month is required (YYYY-MM)")
    if PayrollBatch.query.filter(PayrollBatch.month == month, PayrollBatch.status != "cancelled").first():
        return error(f"a payroll batch for {month} already exists", 409)
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    if not employees:
        return error("no active employees found")

    batch = PayrollBatch(
        month=month, status="draft", notes=data.get("notes") or None,
        created_by=user.id, creator_name_snapshot=user.name,
    )
    for employee in employees:
        salary = money(employee.salary)
        deduction_lines = build_deduction_lines(salary, employee=employee, month=month)
        employee_deductions = money(sum((dl.amount for dl in deduction_lines if dl.side == "employee"), Decimal(0)))
        employer_cost = money(sum((dl.amount for dl in deduction_lines if dl.side == "employer"), Decimal(0)))
        line = PayrollRun(
            month=month, employee_id=employee.id, salary_amount=salary, deductions=employee_deductions,
            employer_cost=employer_cost, net_pay=money(salary - employee_deductions),
            created_by=user.id, creator_name_snapshot=user.name, status="draft",
        )
        line.deduction_lines = deduction_lines
        batch.lines.append(line)
    db.session.add(batch)
    db.session.flush()
    audit(user, "CREATE", "payroll", batch.id, f"month={month}, lines={len(employees)}")
    db.session.commit()
    return jsonify({"payroll_batch": batch_json(batch)}), 201


def editable_batch(batch_id, line_id=None):
    """Phase 2 item 4: locked (SELECT ... FOR UPDATE) so two concurrent
    finalize (or finalize + cancel) requests for the same batch can't both
    pass the draft check and both apply."""
    batch = PayrollBatch.query.filter_by(id=batch_id).with_for_update().first()
    if batch is None:
        from flask import abort
        abort(404)
    if batch.status != "draft":
        return None, None, error(f"this payroll batch is already {batch.status}", 409)
    if line_id is None:
        return batch, None, None
    line = PayrollRun.query.filter_by(id=line_id, batch_id=batch.id).first_or_404()
    return batch, line, None


@payroll_bp.patch("/<int:batch_id>/lines/<int:line_id>")
@permission_required("payroll:manage")
def edit_line(user, batch_id, line_id):
    batch, line, denied = editable_batch(batch_id, line_id)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        salary = parse_money(data["salary_amount"], "salary_amount") if "salary_amount" in data else money(line.salary_amount)
        manual_deductions = parse_money(data["deductions"], "deductions") if "deductions" in data else None
    except ValueError as exc:
        return error(str(exc))
    if manual_deductions is not None and manual_deductions > salary:
        return error("deductions cannot be greater than the salary")
    before = f"salary={line.salary_amount}, deductions={line.deductions}, net={line.net_pay}"
    line.salary_amount = salary
    if manual_deductions is not None:
        # An explicit override replaces the itemized lines with a single
        # "Manual adjustment" line, so the payslip still adds up exactly
        # (Part 5.2's per-line display always sums to the same deductions
        # total it's shown next to).
        line.deduction_lines = (
            [PayrollDeductionLine(name_snapshot="Manual adjustment", side="employee", amount=manual_deductions)]
            if manual_deductions > 0 else []
        )
        line.deductions = manual_deductions
        line.employer_cost = Decimal(0)
    else:
        line.deduction_lines = build_deduction_lines(salary, employee=line.employee, month=line.month)
        line.deductions = money(sum((dl.amount for dl in line.deduction_lines if dl.side == "employee"), Decimal(0)))
        line.employer_cost = money(sum((dl.amount for dl in line.deduction_lines if dl.side == "employer"), Decimal(0)))
    if line.deductions > salary:
        return error("deductions cannot be greater than the salary")
    line.net_pay = money(salary - line.deductions)
    audit(user, "EDIT_LINE", "payroll", batch.id,
          f"{line.employee.name if line.employee else line.employee_id}: {before} -> "
          f"salary={line.salary_amount}, deductions={line.deductions}, net={line.net_pay}")
    db.session.commit()
    return jsonify({"payroll_batch": batch_json(batch)})


@payroll_bp.patch("/<int:batch_id>/lines/<int:line_id>/deduction-lines/<int:dl_id>")
@permission_required("payroll:manage")
def adjust_deduction_line(user, batch_id, line_id, dl_id):
    """Change one deduction line's amount for THIS RUN ONLY — the standing
    EmployeeDeduction/DeductionType it came from is never touched. Accepts
    either `amount` directly, or `rate` (recomputed as gross x rate/100,
    rounded up) for a percentage-based line. The result is clamped to what
    is actually available: never below zero, never more than the salary
    minus every other deduction already on this line — so the total can
    never exceed the salary. Marks the line 'Adjusted' and recomputes the
    run's deductions/employer_cost/net_pay totals."""
    batch, line, denied = editable_batch(batch_id, line_id)
    if denied:
        return denied
    dl = PayrollDeductionLine.query.filter_by(id=dl_id, payroll_run_id=line.id).first_or_404()
    data = request.get_json(silent=True) or {}
    other_total = money(sum((d.amount for d in line.deduction_lines if d.side == "employee" and d.id != dl.id), Decimal(0)))
    available = max(money(line.salary_amount) - other_total, Decimal(0))
    if "rate" in data:
        try:
            rate = Decimal(str(data["rate"]))
        except Exception:
            return error("rate must be a valid number")
        if rate < 0 or rate > 100:
            return error("rate must be between 0 and 100")
        new_amount = whole_up(money(line.salary_amount) * rate / Decimal(100))
    else:
        try:
            new_amount = parse_money(data.get("amount"), "amount")
        except ValueError as exc:
            return error(str(exc))
    new_amount = min(max(new_amount, Decimal(0)), available)
    before = dl.amount
    dl.amount = new_amount
    dl.is_adjusted = True
    line.deductions = money(sum((d.amount for d in line.deduction_lines if d.side == "employee"), Decimal(0)))
    line.employer_cost = money(sum((d.amount for d in line.deduction_lines if d.side == "employer"), Decimal(0)))
    line.net_pay = money(money(line.salary_amount) - line.deductions)
    audit(user, "ADJUST_DEDUCTION_LINE", "payroll", batch.id,
          f"{line.employee.name if line.employee else line.employee_id}: {dl.name_snapshot} {before} -> {new_amount} (this run only)")
    db.session.commit()
    return jsonify({"payroll_batch": batch_json(batch)})


@payroll_bp.delete("/<int:batch_id>/lines/<int:line_id>")
@permission_required("payroll:manage")
def remove_line(user, batch_id, line_id):
    batch, line, denied = editable_batch(batch_id, line_id)
    if denied:
        return denied
    if len(batch.lines) <= 1:
        return error("a batch needs at least one line — cancel the batch instead")
    name = line.employee.name if line.employee else line.employee_id
    batch.lines.remove(line)
    audit(user, "REMOVE_LINE", "payroll", batch.id, f"removed {name} (net {line.net_pay})")
    db.session.commit()
    return jsonify({"payroll_batch": batch_json(batch)})


@payroll_bp.post("/<int:batch_id>/finalize")
@permission_required("payroll:manage")
def finalize_batch(user, batch_id):
    """One action: mark the batch (and every line) paid. No second approver."""
    batch, _line, denied = editable_batch(batch_id)
    if denied:
        return denied
    over = [line for line in batch.lines if money(line.deductions) > money(line.salary_amount)]
    if over:
        names = ", ".join(line.employee.name if line.employee else str(line.employee_id) for line in over)
        return error(f"Deductions exceed gross pay for: {names}. Fix those lines before finalizing.")
    try:
        # Phase 2 item 4: batch_json(batch) below is this request's first
        # access of line.employee for each line, which can autoflush (and
        # conflict) before the explicit commit() is ever reached.
        batch.status = "paid"
        batch.finalized_by = user.id
        batch.finalizer_name_snapshot = user.name
        batch.finalized_at = datetime.utcnow()
        for line in batch.lines:
            line.status = "paid"
            for dl in line.deduction_lines:
                if dl.employee_deduction_id is None:
                    continue
                assignment = EmployeeDeduction.query.get(dl.employee_deduction_id)
                if assignment is not None and assignment.remaining_balance is not None:
                    assignment.remaining_balance = money(max(assignment.remaining_balance - dl.amount, Decimal(0)))
                    if assignment.remaining_balance <= 0:
                        assignment.is_active = False
        audit(user, "FINALIZE", "payroll", batch.id, f"month={batch.month}, net={batch_json(batch)['total_net']}")
        db.session.commit()
    except StaleDataError:
        # Phase 2 item 4: another finalize/cancel for this batch won the
        # race between our lock and our commit.
        db.session.rollback()
        fresh = PayrollBatch.query.get(batch_id)
        status = fresh.status if fresh else "unknown"
        return error(f"this payroll batch is already {status}", 409)
    return jsonify({"payroll_batch": batch_json(batch)})


@payroll_bp.post("/<int:batch_id>/cancel")
@permission_required("payroll:manage")
def cancel_batch(user, batch_id):
    batch, _line, denied = editable_batch(batch_id)
    if denied:
        return denied
    try:
        batch.status = "cancelled"
        audit(user, "CANCEL", "payroll", batch.id, f"month={batch.month}")
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        fresh = PayrollBatch.query.get(batch_id)
        status = fresh.status if fresh else "unknown"
        return error(f"this payroll batch is already {status}", 409)
    return jsonify({"payroll_batch": batch_json(batch)})


def payslip_line(user, line_id):
    """A line whose payslip this user may see: payroll staff, or the employee themselves."""
    line = PayrollRun.query.get_or_404(line_id)
    own = line.employee is not None and line.employee.user_id == user.id
    if not own and not has_permission(user, "payroll:manage"):
        return None, error("You don't have permission to do this.", 403)
    if line.batch is None or line.batch.status != "paid":
        return None, error("payslips are available once the payroll batch is finalized", 409)
    return line, None


@payroll_bp.get("/lines/<int:line_id>/payslip")
@auth_required
def download_payslip(user, line_id):
    line, denied = payslip_line(user, line_id)
    if denied:
        return denied
    return send_file(
        payslip_pdf(line), as_attachment=True,
        download_name=f"payslip-{line.month}-{(line.employee.name if line.employee else line.id)}.pdf".replace(" ", "-"),
        mimetype="application/pdf",
    )



def _send_one_payslip(user, line, resend=False):
    """Returns (ok, message, status_code). Never sends a second time for
    the same line unless `resend` is explicitly True — the one guard both
    the single "Send" action and "Email all payslips" share, so neither
    path can silently double-send."""
    employee = line.employee
    if line.payslip_sent_at and not resend:
        return False, f"{employee.name if employee else 'This employee'} was already sent this payslip — choose Resend to send it again.", 409
    address = (employee.email if employee else None) or (employee.user.email if employee and employee.user else None)
    if not address:
        return False, f"{employee.name if employee else 'This employee'} has no email address on file", 400
    filename = f"payslip-{line.month}.pdf"
    result = send_email("payslip", address, {
        "employee_name": employee.name, "month": line.month, "filename": filename,
        "pdf_base64": base64.b64encode(payslip_pdf(line).getvalue()).decode("ascii"),
    })
    if result.get("status") != "sent":
        return False, "The payslip email could not be sent — please try again or download the PDF.", 502
    line.payslip_sent_at = datetime.utcnow()
    audit(user, "SEND_PAYSLIP", "payroll", line.batch_id, f"{employee.name} <{address}>" + (" (resend)" if resend else ""))
    return True, f"Payslip sent to {address}", 200


@payroll_bp.post("/lines/<int:line_id>/payslip/send")
@permission_required("payroll:manage")
def send_payslip(user, line_id):
    line, denied = payslip_line(user, line_id)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    ok, message, status = _send_one_payslip(user, line, resend=bool(data.get("resend")))
    if not ok:
        return error(message, status)
    db.session.commit()
    return jsonify({"message": message})


@payroll_bp.post("/<int:batch_id>/payslips/send-all")
@permission_required("payroll:manage")
def send_all_payslips(user, batch_id):
    """Each employee gets ONLY their own payslip (never the combined PDF) —
    already-sent lines are skipped, not resent, unless the caller passes
    resend. Written to the audit log once for the whole batch action."""
    batch = PayrollBatch.query.get_or_404(batch_id)
    if batch.status != "paid":
        return error("payslips can only be emailed once the payroll batch is finalized", 409)
    data = request.get_json(silent=True) or {}
    resend = bool(data.get("resend"))
    results = []
    sent = failed = 0
    for line in batch.lines:
        ok, message, _status = _send_one_payslip(user, line, resend=resend)
        name = line.employee.name if line.employee else f"Employee #{line.employee_id}"
        results.append({"employee_name": name, "sent": ok, "message": message})
        if ok:
            sent += 1
        else:
            failed += 1
    audit(user, "SEND_ALL_PAYSLIPS", "payroll", batch.id, f"month={batch.month}, sent={sent}, failed={failed}")
    db.session.commit()
    return jsonify({"sent": sent, "failed": failed, "results": results})
