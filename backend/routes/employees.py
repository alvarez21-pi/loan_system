from datetime import date

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Employee, User
from routes.auth import auth_required
from routes.operations import audit, error, json_row, parse_date, parse_money, permission_required
from services.accounts import AccountError, create_login, queue_setup_email
from services.permissions import assignable_roles_for, has_permission

employees_bp = Blueprint("employees", __name__, url_prefix="/api/employees")


def account_creator_required(fn):
    """Gate for actions that create/attach a LOGIN (not an HR record): any
    actor who can hand out at least one tier (ceo, head_manager, or a
    department_manager of ANY department) — not `employees:manage`, which is
    HR-specific and would otherwise wrongly block e.g. a Loans Manager from
    creating a login for their own department's staff (Part 11). The actual
    role+department being requested is still validated by create_login()'s
    own can_create_tier() check, exactly as for the Users page."""
    @auth_required
    def wrapped(user, *args, **kwargs):
        if not assignable_roles_for(user):
            return error("You don't have permission to do this.", 403)
        return fn(user, *args, **kwargs)
    wrapped.__name__ = fn.__name__
    return wrapped


def employee_json(employee, viewer):
    data = json_row(employee)
    if not has_permission(viewer, "employees:manage") and employee.user_id != viewer.id:
        data.pop("salary", None)  # pay is for HR/CEO/manager or the employee themselves
    user = employee.user
    data["linked_user_name"] = user.name if user else None
    data["linked_user_email"] = user.email if user else None
    data["linked_user_role"] = user.role if user else None
    data["linked_user_department"] = user.department if user else None
    data["linked_user_verified"] = user.email_verified if user else None
    return data


def link_employee_to_user(employee, user):
    """Connect an existing Employee and User after the fact (either side started it)."""
    if employee.user_id is not None:
        raise ValueError(f"{employee.name} is already linked to a login account")
    if user.employee is not None:
        raise ValueError(f"{user.name} is already linked to an employee record")
    employee.user_id = user.id
    if not employee.email:
        employee.email = user.email


def duplicate_warning(name, phone, exclude_id=None):
    """Same name + phone already on file: not blocked, just flagged so the
    creator can double-check before adding a duplicate (Part 2.4)."""
    query = Employee.query.filter(Employee.name.ilike(name.strip()), Employee.phone == phone.strip())
    if exclude_id:
        query = query.filter(Employee.id != exclude_id)
    existing = query.first()
    return f"An employee named '{name}' with this phone number already exists (#{existing.id})." if existing else None


@employees_bp.get("")
@auth_required
def list_employees(user):
    query = Employee.query.order_by(Employee.name)
    if not has_permission(user, "employees:manage"):
        # Everyone else only ever needs their own record (e.g. to file leave).
        query = query.filter_by(user_id=user.id)
    return jsonify({"employees": [employee_json(row, user) for row in query.all()]})


@employees_bp.post("")
@permission_required("employees:manage")
def create_employee(user):
    data = request.get_json(silent=True) or {}
    try:
        employee = Employee(
            name=str(data["name"]).strip(),
            job_title=str(data.get("job_title", data.get("role")) or "").strip(),
            salary=parse_money(data.get("salary"), "salary"),
            phone=str(data["phone"]).strip(),
            email=(str(data.get("email")).strip().lower() if data.get("email") else None),
            start_date=parse_date(data.get("start_date", data.get("hire_date")), "start_date"),
            is_active=True,
        )
        if not employee.name or not employee.phone:
            raise ValueError("name and phone are required")
        if not employee.job_title:
            raise ValueError("job_title is required")
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))

    warning = duplicate_warning(employee.name, employee.phone)

    # Optional login for this employee (unchecked by default: not every
    # employee needs system access). Both records commit together or not at all.
    new_user = None
    if data.get("create_user") is True:
        try:
            new_user = create_login(
                user,
                name=employee.name,
                email=data.get("email"),
                phone=employee.phone,
                role=data.get("role", "maker"),
                department=data.get("department"),
            )
        except AccountError as exc:
            return error(exc.message, exc.status)
        employee.user_id = new_user.id
        employee.email = new_user.email

    db.session.add(employee)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return error("could not save the employee", 409)
    audit(user, "CREATE", "employees", employee.id)
    db.session.commit()
    if new_user is not None:
        queue_setup_email(new_user)
    body = {"employee": employee_json(employee, user)}
    if new_user is not None:
        body["user"] = new_user.to_dict()
    if warning:
        body["warning"] = warning
    return jsonify(body), 201


@employees_bp.route("/<int:employee_id>", methods=["PUT", "PATCH"])
@permission_required("employees:manage")
def update_employee(user, employee_id):
    """Edit any field after creation, however the employee came to exist."""
    employee = Employee.query.get_or_404(employee_id)
    data = request.get_json(silent=True) or {}
    warning = None
    try:
        if "name" in data:
            employee.name = str(data["name"]).strip()
        if "phone" in data:
            employee.phone = str(data["phone"]).strip()
        if "job_title" in data:
            employee.job_title = str(data["job_title"]).strip()
        if "email" in data:
            employee.email = str(data["email"]).strip().lower() if data["email"] else None
        if "salary" in data:
            employee.salary = parse_money(data["salary"], "salary")
        if "start_date" in data:
            employee.start_date = parse_date(data["start_date"], "start_date")
        if not employee.name or not employee.phone or not employee.job_title:
            raise ValueError("name, phone and job_title cannot be empty")
        if "name" in data or "phone" in data:
            warning = duplicate_warning(employee.name, employee.phone, exclude_id=employee.id)
        if "is_active" in data:
            if data["is_active"] is False:
                blocked = deactivation_block(employee)
                if blocked:
                    return blocked
            employee.is_active = bool(data["is_active"])
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return error(str(exc))
    audit(user, "UPDATE", "employees", employee.id)
    db.session.commit()
    body = {"employee": employee_json(employee, user)}
    if warning:
        body["warning"] = warning
    return jsonify(body)


def deactivation_block(employee):
    if employee.user is not None and employee.user.role == "ceo":
        return error("the CEO's employee record cannot be deactivated", 403)
    return None


@employees_bp.delete("/<int:employee_id>")
@permission_required("employees:manage")
def deactivate_employee(user, employee_id):
    """Soft delete: the record stays for payroll/leave history, out of new payroll runs."""
    employee = Employee.query.get_or_404(employee_id)
    blocked = deactivation_block(employee)
    if blocked:
        return blocked
    employee.is_active = False
    audit(user, "DEACTIVATE", "employees", employee.id, f"name={employee.name}")
    db.session.commit()
    return jsonify({"employee": employee_json(employee, user)})


@employees_bp.post("/<int:employee_id>/link-user")
@account_creator_required
def link_user(user, employee_id):
    employee = Employee.query.get_or_404(employee_id)
    target = User.query.get((request.get_json(silent=True) or {}).get("user_id"))
    if target is None:
        return error("user not found", 404)
    try:
        link_employee_to_user(employee, target)
    except ValueError as exc:
        return error(str(exc), 409)
    audit(user, "LINK_USER", "employees", employee.id, f"user_id={target.id}")
    db.session.commit()
    return jsonify({"employee": employee_json(employee, user)})


@employees_bp.post("/<int:employee_id>/create-login")
@account_creator_required
def create_login_for_employee(user, employee_id):
    """"Create login" action on an employee who has none yet: one user, linked
    to THIS employee (never a second Employee row), prefilled with their email,
    verification email sent (Part 2.2)."""
    employee = Employee.query.get_or_404(employee_id)
    if employee.user_id is not None:
        return error(f"{employee.name} already has a login account", 409)
    data = request.get_json(silent=True) or {}
    email = data.get("email") or employee.email
    if not email:
        return error("this employee has no email on file — add one first")
    try:
        new_user = create_login(
            user,
            name=employee.name,
            email=email,
            phone=employee.phone,
            role=data.get("role", "maker"),
            department=data.get("department"),
        )
    except AccountError as exc:
        return error(exc.message, exc.status)
    employee.user_id = new_user.id
    employee.email = new_user.email
    audit(user, "CREATE_LOGIN", "employees", employee.id, f"user_id={new_user.id}")
    db.session.commit()
    queue_setup_email(new_user)
    return jsonify({"employee": employee_json(employee, user), "user": new_user.to_dict()}), 201
