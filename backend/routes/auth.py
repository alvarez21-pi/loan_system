from functools import wraps
from email.utils import parseaddr
import os
import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import User
from services.email_client import send_email


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _normalize_email(value):
    if not isinstance(value, str) or not value.strip():
        return None
    email = value.strip().lower()
    if parseaddr(email)[1] != email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return None
    return email


def _reset_serializer():
    return URLSafeTimedSerializer(
        current_app.config["JWT_SECRET_KEY"],
        salt="loan-system-password-reset",
    )


def _reset_token(user, purpose="password_reset"):
    return _reset_serializer().dumps({"user_id": user.id, "purpose": purpose})


def _setup_link(user):
    token = _reset_token(user, "account_setup")
    return f'{current_app.config["FRONTEND_URL"]}/?setup={token}'


def auth_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        current_user = User.query.get(int(user_id))
        if current_user is None or not current_user.is_active:
            return jsonify({"message": "user is inactive or no longer exists"}), 401
        return fn(current_user, *args, **kwargs)

    return wrapper


@auth_bp.post("/register")
@auth_required
def register(admin):
    if admin.role != "admin":
        return jsonify({"message": "admin role required"}), 403
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    email = _normalize_email(data.get("email"))
    phone = data.get("phone")

    if not all(isinstance(value, str) and value.strip() for value in (name, phone)):
        return jsonify({"message": "name, email, and phone are required"}), 400
    if email is None:
        return jsonify({"message": "a valid email is required"}), 400
    role = data.get("role", "maker")
    if role not in {"maker", "checker"}:
        return jsonify({"message": "role must be maker or checker"}), 400
    if User.query.filter((User.email == email) | (User.phone == phone.strip())).first():
        return jsonify({"message": "email or phone is already registered"}), 409

    user = User(name=name.strip(), email=email, phone=phone.strip(), role=role, email_verified=False)
    user.set_password(os.urandom(32).hex())
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "email or phone is already registered"}), 409

    try:
        send_email(
            "verification",
            user.email,
            {"name": user.name, "verify_link": _setup_link(user)},
        )
    except Exception:
        current_app.logger.exception("verification email could not be sent")

    return jsonify({"user": user.to_dict()}), 201


@auth_bp.post("/password-reset/request")
def request_password_reset():
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    if email is None:
        return jsonify({"message": "if an account exists, a reset email has been sent"}), 202

    user = User.query.filter_by(email=email, is_active=True).first()
    if user is not None:
        reset_token = _reset_token(user)
        send_email(
            "password_reset",
            user.email,
            {
                "name": user.name,
                "reset_token": reset_token,
                "reset_link": f'{current_app.config["FRONTEND_URL"]}/?token={reset_token}',
            },
        )

    return jsonify({"message": "if an account exists, a reset email has been sent"}), 202


@auth_bp.post("/password-reset/confirm")
def confirm_password_reset():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    password = data.get("password")
    if not isinstance(token, str) or not token or not isinstance(password, str):
        return jsonify({"message": "token and password are required"}), 400
    if len(password) < 8:
        return jsonify({"message": "password must be at least 8 characters"}), 400

    try:
        payload = _reset_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return jsonify({"message": "invalid or expired reset token"}), 400

    user = User.query.get(payload.get("user_id"))
    if user is None or not user.is_active:
        return jsonify({"message": "invalid or expired reset token"}), 400

    if payload.get("purpose") not in {"password_reset", "account_setup"}:
        return jsonify({"message": "invalid or expired reset token"}), 400
    user.set_password(password)
    if payload.get("purpose") == "account_setup":
        user.email_verified = True
    db.session.commit()
    return jsonify({"message": "password has been reset"}), 200


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "email and password are required"}), 400

    user = User.query.filter_by(email=email, is_active=True).first()
    if user is None or not user.check_password(password):
        return jsonify({"message": "invalid credentials"}), 401
    if not user.email_verified:
        return jsonify({"message": "verify your email before signing in"}), 403

    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role},
    )
    return jsonify({"access_token": token, "user": user.to_dict()}), 200
