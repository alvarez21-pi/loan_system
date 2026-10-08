from flask import Blueprint, jsonify, request

from extensions import db
from models import AuditLog, Employee, User
from routes.auth import auth_required
from services.accounts import AccountError, parse_department, queue_setup_email
from services.permissions import (
    UNSCOPED_ROLES,
    assignable_roles_for,
    can_create_tier,
    can_manage_user,
)
from services.listing import paginate
from services.scheduler import retention_days

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


def user_manager(fn):
    """Anyone who could ever hand out at least one tier gets into the Users
    page — ceo, head_manager, or a department_manager (scoped to their own
    department's checker/maker accounts only, enforced below)."""
    @auth_required
    def wrapper(user, *args, **kwargs):
        if not assignable_roles_for(user):
            return jsonify({"message": "You don't have permission to do this."}), 403
        return fn(user, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


def audit(actor, action, table, record_id, details=None):
    db.session.add(
        AuditLog(
            user_id=actor.id,
            actor_name_snapshot=actor.name,
            actor_email_snapshot=actor.email,
            action=action,
            table_name=table,
            record_id=record_id,
            details=details,
        )
    )


def guard_ceo(target):
    """CEO accounts are fixed — no one, including another CEO, can change them."""
    if target.role == "ceo":
        return jsonify({"message": "ceo accounts cannot be modified"}), 403
    return None


def guard_can_manage(actor, target, new_role=None, new_department=None):
    """Part 1's creation/management hierarchy, applied to an EXISTING account.
    Checked against the account's role/department AS IT WOULD BE AFTER the
    change, so an actor can never grant a tier they aren't allowed to create."""
    role = new_role if new_role is not None else target.role
    department = new_department if new_department is not None else target.department
    if not can_manage_user(actor, target) or not can_create_tier(actor, role, department):
        return jsonify({"message": "You don't have permission to do this."}), 403
    return None


@users_bp.get("")
@user_manager
def list_users(user):
    query = User.query
    if user.role not in UNSCOPED_ROLES:
        # A department_manager only ever manages their own department's staff
        # (plus seeing their own row) — never another department's, never CEO.
        query = query.filter(db.or_(User.department == user.department, User.id == user.id))
    rows, pagination = paginate(
        query,
        request.args,
        searchable=(User.name, User.email, User.phone),
        sortable={"name": User.name, "email": User.email, "role": User.role},
        default_sort=User.name,
    )
    body = {
        "users": [row.to_dict() for row in rows],
        "retention_days": retention_days(),
        "assignable_roles": assignable_roles_for(user),
    }
    if pagination is not None:
        body["pagination"] = pagination
    return jsonify(body)


@users_bp.patch("/<int:user_id>")
@user_manager
def update_user(actor, user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    blocked = guard_ceo(user)
    if blocked:
        return blocked

    try:
        new_role = data["role"] if "role" in data else None
        new_department = parse_department(data["department"]) if "department" in data else None
    except AccountError as exc:
        return jsonify({"message": exc.message}), exc.status

    blocked = guard_can_manage(actor, user, new_role=new_role, new_department=new_department if "department" in data else None)
    if blocked:
        return blocked

    if new_role is not None and new_role != user.role:
        audit(actor, "UPDATE_ROLE", "users", user.id, f"{user.role} -> {new_role}")
        user.role = new_role
    if "department" in data and new_department != user.department:
        audit(actor, "UPDATE_DEPARTMENT", "users", user.id, f"{user.department} -> {new_department}")
        user.department = new_department

    if "is_active" in data:
        if data["is_active"] is False and user.is_active:
            user.deactivate()
            audit(actor, "DEACTIVATE", "users", user.id, f"name={user.name}, email={user.email}")
        elif data["is_active"] is True and not user.is_active:
            user.reactivate()
            audit(actor, "REACTIVATE", "users", user.id, f"name={user.name}, email={user.email}")

    db.session.commit()
    return jsonify({"user": user.to_dict()})


@users_bp.post("/<int:user_id>/resend-verification")
@user_manager
def resend_verification(actor, user_id):
    user = User.query.get_or_404(user_id)
    if user.email_verified:
        return jsonify({"message": f"{user.name} is already verified"}), 409
    queue_setup_email(user)
    audit(actor, "RESEND_VERIFICATION", "users", user.id, user.email)
    db.session.commit()
    return jsonify({"message": f"a new verification link has been sent to {user.email}"})


@users_bp.post("/<int:user_id>/link-employee")
@user_manager
def link_employee(actor, user_id):
    """Retroactively connect an existing login to an existing Employee record."""
    from routes.employees import link_employee_to_user

    user = User.query.get_or_404(user_id)
    employee = Employee.query.get((request.get_json(silent=True) or {}).get("employee_id"))
    if employee is None:
        return jsonify({"message": "employee not found"}), 404
    try:
        link_employee_to_user(employee, user)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 409
    audit(actor, "LINK_EMPLOYEE", "users", user.id, f"employee_id={employee.id}")
    db.session.commit()
    return jsonify({"user": user.to_dict()})


@users_bp.delete("/<int:user_id>")
@user_manager
def delete_user(actor, user_id):
    user = User.query.get_or_404(user_id)

    blocked = guard_ceo(user)
    if blocked:
        return blocked
    blocked = guard_can_manage(actor, user)
    if blocked:
        return blocked

    audit(actor, "DELETE", "users", user.id, f"name={user.name}, email={user.email}")
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "user deleted"})
