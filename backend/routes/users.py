from flask import Blueprint, jsonify, request

from extensions import db
from models import User
from routes.auth import auth_required

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


def admin_only(fn):
    @auth_required
    def wrapper(user, *args, **kwargs):
        if user.role != "admin":
            return jsonify({"message": "admin role required"}), 403
        return fn(user, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


@users_bp.get("")
@admin_only
def list_users(_admin):
    return jsonify({"users": [user.to_dict() for user in User.query.order_by(User.name).all()]})


@users_bp.patch("/<int:user_id>")
@admin_only
def update_user(_admin, user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    if data.get("is_active") is False:
        if user.role == "admin":
            return jsonify({"message": "admin users cannot be deactivated here"}), 400
        user.is_active = False
    db.session.commit()
    return jsonify({"user": user.to_dict()})
