from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Employee, User
from services.accounts import (
    LINKABLE_ROLES,
    AccountError,
    create_login,
    normalize_email as _normalize_email,
    parse_department,
    queue_setup_email,
    reset_link as _reset_link,
    reset_serializer as _reset_serializer,
    reset_token as _reset_token,
    send_email_async,
)
from services.password_policy import validate_password_strength
from services.permissions import assignable_roles_for
from services.rate_limit import (
    RateLimited,
    check as rate_limit_check,
    identifiers_for,
    rate_limit_response,
    record_failure as rate_limit_failure,
    record_success as rate_limit_success,
)


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Phase 2 item 3: endpoints an account with must_change_password=True may
# still reach — everything else is blocked until the password is changed.
MUST_CHANGE_PASSWORD_ALLOWLIST = {"auth.me", "auth.change_password"}


def verification_ttl_hours():
    try:
        return float(current_app.config.get("VERIFICATION_TOKEN_TTL_HOURS", 24))
    except (TypeError, ValueError):
        return 24.0


def password_reset_ttl_minutes():
    try:
        return float(current_app.config.get("PASSWORD_RESET_TTL_MINUTES", 60))
    except (TypeError, ValueError):
        return 60.0


def auth_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        current_user = User.query.get(int(user_id))
        if current_user is None or not current_user.is_active:
            return jsonify({"message": "Your session expired. Please sign in again."}), 401
        if current_user.must_change_password and request.endpoint not in MUST_CHANGE_PASSWORD_ALLOWLIST:
            return jsonify({
                "message": "You must set a new password before continuing.",
                "must_change_password": True,
            }), 403
        return fn(current_user, *args, **kwargs)

    return wrapper


@auth_bp.get("/me")
@auth_required
def me(user):
    """The server's view of who this token belongs to — role AND the full
    permission set, so the frontend never has to guess what it can show."""
    return jsonify({"user": user.to_dict()})


@auth_bp.post("/change-password")
@auth_required
def change_password(user):
    """The one way out of must_change_password=True — also usable any time
    by any already-logged-in user to change their own password voluntarily."""
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    if not current_password or not user.check_password(current_password):
        return jsonify({"message": "Current password is incorrect."}), 401
    try:
        validate_password_strength(new_password, field="new_password")
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    user.set_password(new_password)
    user.must_change_password = False
    user.credentials_version += 1  # invalidates any outstanding setup/reset link
    db.session.commit()
    return jsonify({"user": user.to_dict()})


@auth_bp.post("/register")
@auth_required
def register(creator):
    if not assignable_roles_for(creator):
        return jsonify({"message": "You don't have permission to do this."}), 403
    data = request.get_json(silent=True) or {}
    role = data.get("role", "maker")

    job_title = data.get("job_title")
    if job_title is not None and not isinstance(job_title, str):
        return jsonify({"message": "job_title must be text"}), 400

    salary = Decimal("0")
    if data.get("salary") not in (None, ""):
        try:
            salary = Decimal(str(data["salary"]))
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({"message": "salary must be a valid number"}), 400
        if salary < 0:
            return jsonify({"message": "salary must not be negative"}), 400

    # Employee linkage is one explicit choice, not a checkbox default (Part 2.1):
    # "create" (default) makes a new Employee, "link" attaches an existing
    # employee who has no login yet, "none" makes no Employee record at all.
    employee_option = data.get("employee_option", "create")
    if employee_option not in {"create", "link", "none"}:
        return jsonify({"message": "employee_option must be create, link, or none"}), 400
    if employee_option != "none" and role not in LINKABLE_ROLES:
        employee_option = "none"

    link_target = None
    if employee_option == "link":
        link_target = Employee.query.get(data.get("employee_id"))
        if link_target is None:
            return jsonify({"message": "employee not found"}), 404
        if link_target.user_id is not None:
            return jsonify({"message": f"{link_target.name} is already linked to a login account"}), 409

    try:
        department = parse_department(data.get("department"))
        user = create_login(
            creator,
            name=data.get("name"),
            email=data.get("email"),
            phone=data.get("phone"),
            role=role,
            department=department,
        )
    except AccountError as exc:
        return jsonify({"message": exc.message}), exc.status

    employee = None
    if employee_option == "create":
        # Permission role (functional) and job_title (descriptive) are independent —
        # job_title never changes what the account can do, only how it's labeled.
        employee = Employee(
            name=user.name,
            job_title=(job_title or user.display_role),
            salary=salary,
            phone=user.phone,
            email=user.email,
            start_date=date.today(),
            is_active=True,
            user_id=user.id,
        )
        db.session.add(employee)
    elif employee_option == "link":
        link_target.user_id = user.id
        if not link_target.email:
            link_target.email = user.email
        employee = link_target

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "email or phone is already registered"}), 409

    queue_setup_email(user)

    response = {"user": user.to_dict()}
    if employee is not None:
        response["employee"] = {
            "id": employee.id,
            "name": employee.name,
            "job_title": employee.job_title,
            "salary": float(employee.salary),
        }
    return jsonify(response), 201


@auth_bp.post("/resend-verification")
def resend_verification():
    """Rate-limited-by-genericness: always the same response, whether or not
    the account exists or is already verified, so the endpoint can't be used
    to probe which emails are registered (Part 8.3).

    Phase 2 item 7: also rate-limited by IP + the submitted email — every
    call counts (there's no success/failure split to key off, since the
    response never varies), so the 202 body stays identical, only a 429
    (itself revealing nothing about whether the email exists) can differ.
    """
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    identifiers = identifiers_for(email)
    try:
        rate_limit_check("resend_verification", identifiers)
    except RateLimited:
        return rate_limit_response()
    rate_limit_failure("resend_verification", identifiers)
    generic = jsonify({"message": "if an account needs verification, a new link has been sent"}), 202
    if email is None:
        return generic
    user = User.query.filter_by(email=email, is_active=True).first()
    if user is not None and not user.email_verified:
        queue_setup_email(user)
    return generic


@auth_bp.post("/password-reset/request")
def request_password_reset():
    """Phase 2 item 7: same rate-limit treatment as resend_verification()
    above, for the same reason (a uniformly-generic response either way)."""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    identifiers = identifiers_for(email)
    try:
        rate_limit_check("password_reset_request", identifiers)
    except RateLimited:
        return rate_limit_response()
    rate_limit_failure("password_reset_request", identifiers)
    if email is None:
        return jsonify({"message": "if an account exists, a reset email has been sent"}), 202

    user = User.query.filter_by(email=email, is_active=True).first()
    if user is not None:
        send_email_async(
            "password_reset",
            user.email,
            {
                "name": user.name,
                "reset_link": _reset_link(user),
            },
        )

    return jsonify({"message": "if an account exists, a reset email has been sent"}), 202


def _load_reset_payload(token):
    """Validate a setup/reset token end-to-end WITHOUT consuming it:
    signature, per-purpose TTL, a real+active user, and single-use (the
    token's embedded credentials version must still match the user's
    current one). Returns (user, purpose, None) on success, or
    (None, None, (body, status)) for the caller to return as-is.

    Shared by /password-reset/validate (the pre-check the set-password page
    must call before ever rendering the form — Part 2) and
    /password-reset/confirm (which additionally consumes the token). Neither
    endpoint is decorated with @auth_required — both are, and must stay,
    fully public and token-only: whatever Authorization header or session the
    browser happens to be carrying is never read here.
    """
    if not isinstance(token, str) or not token:
        return None, None, ({"message": "This link is invalid.", "expired": True}, 400)
    try:
        # account_setup tokens (new-user verification) and password_reset
        # tokens (forgot-password) get their own configurable lifetimes —
        # peek the purpose first, without enforcing a TTL yet.
        payload = _reset_serializer().loads(token, max_age=None)
    except (BadSignature, SignatureExpired):
        return None, None, ({"message": "This link has expired or is invalid.", "expired": True}, 400)

    purpose = payload.get("purpose")
    if purpose not in {"password_reset", "account_setup"}:
        return None, None, ({"message": "This link has expired or is invalid.", "expired": True}, 400)
    max_age = (
        verification_ttl_hours() * 3600 if purpose == "account_setup" else password_reset_ttl_minutes() * 60
    )
    try:
        payload = _reset_serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        return None, None, ({"message": "This link has expired. Request a new one below.", "expired": True}, 400)
    except BadSignature:
        return None, None, ({"message": "This link is invalid.", "expired": True}, 400)

    user = User.query.get(payload.get("user_id"))
    if user is None or not user.is_active:
        return None, None, ({"message": "This link has expired or is invalid.", "expired": True}, 400)
    if payload.get("v") != user.credentials_version:
        # The credentials_version this token was issued against has moved on
        # — it (or another link issued before it) has already been used.
        return None, None, ({"message": "This link has already been used. Request a new one below.", "expired": True}, 400)

    return user, purpose, None


@auth_bp.post("/password-reset/validate")
def validate_reset_token():
    """Public, token-only pre-check. The set-password / verification page
    must call this FIRST and only render the form if it comes back valid —
    never show the form on the strength of the URL alone (Part 2).

    Phase 2 item 7: rate-limited by IP (no account identifier is known
    safely from a possibly-forged token) — a brute-force guesser burning
    through tokens is slowed down the same as any other guessing attack.
    """
    data = request.get_json(silent=True) or {}
    identifiers = identifiers_for()
    try:
        rate_limit_check("password_reset_validate", identifiers)
    except RateLimited:
        return rate_limit_response()
    _user, purpose, error = _load_reset_payload(data.get("token"))
    if error:
        rate_limit_failure("password_reset_validate", identifiers)
        body, status = error
        return jsonify(body), status
    return jsonify({"valid": True, "purpose": purpose}), 200


@auth_bp.post("/password-reset/confirm")
def confirm_password_reset():
    # Deliberately not decorated with @auth_required / @jwt_required: this page
    # must behave identically no matter what session/Authorization header the
    # browser happens to be carrying — it is a public, token-only endpoint.
    #
    # Phase 2 item 7: rate-limited by IP, same reasoning as validate_reset_token().
    data = request.get_json(silent=True) or {}
    identifiers = identifiers_for()
    try:
        rate_limit_check("password_reset_confirm", identifiers)
    except RateLimited:
        return rate_limit_response()

    token = data.get("token")
    password = data.get("password")
    if not isinstance(token, str) or not token or not isinstance(password, str):
        rate_limit_failure("password_reset_confirm", identifiers)
        return jsonify({"message": "token and password are required"}), 400
    if len(password) < 8:
        rate_limit_failure("password_reset_confirm", identifiers)
        return jsonify({"message": "password must be at least 8 characters"}), 400

    user, purpose, error = _load_reset_payload(token)
    if error:
        rate_limit_failure("password_reset_confirm", identifiers)
        body, status = error
        return jsonify(body), status

    user.set_password(password)
    user.credentials_version += 1  # this link, and any other outstanding one for this user, is now spent
    if purpose == "account_setup":
        user.email_verified = True
    db.session.commit()
    rate_limit_success("password_reset_confirm", identifiers)
    return jsonify({"message": "password has been set"}), 200


@auth_bp.post("/login")
def login():
    """Phase 2 item 7: rate-limited per-account (the submitted email) AND
    per-IP — the lockout check runs BEFORE the password is even checked, so
    an already-locked account/IP gets the same generic 429 regardless of
    whether this particular password happens to be right; a wrong password
    counts as a failure, a successful login clears the counter."""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password")
    identifiers = identifiers_for(email)
    try:
        rate_limit_check("login", identifiers)
    except RateLimited:
        return rate_limit_response()

    if not email or not password:
        rate_limit_failure("login", identifiers)
        return jsonify({"message": "email and password are required"}), 400

    user = User.query.filter_by(email=email, is_active=True).first()
    if user is None or not user.check_password(password):
        rate_limit_failure("login", identifiers)
        return jsonify({"message": "Incorrect email or password."}), 401
    if not user.email_verified:
        rate_limit_failure("login", identifiers)
        return jsonify(
            {"message": "Please verify your email before logging in. Check your inbox for the verification link."}
        ), 403

    rate_limit_success("login", identifiers)
    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role},
    )
    return jsonify({"access_token": token, "user": user.to_dict()}), 200
