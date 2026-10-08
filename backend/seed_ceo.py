"""Idempotent CEO seed (Part 9.1): safe to run on every deploy.

Creates (or updates) the CEO user from environment variables, plus:
- a linked Employee record (job title "CEO") if one doesn't already exist
- the preloaded asset types, if the table is empty

Phase 2 item 3: CEO_EMAIL and CEO_PASSWORD have NO fallback default any
more — a deploy with either unset refuses to seed at all, rather than
silently creating ceo@example.com / admin12345. The password is checked
against the same strength rule the mandatory change-password endpoint
uses, and the account is flagged must_change_password=True so the real
CEO is forced to pick their own password on first login.
"""
import os
from datetime import date

from app import create_app
from extensions import db
from models import DEFAULT_ASSET_TYPES, AssetType, Employee, User
from services.password_policy import validate_password_strength


def ensure_asset_types():
    if AssetType.query.count() > 0:
        return 0
    for name in DEFAULT_ASSET_TYPES:
        db.session.add(AssetType(name=name, is_active=True))
    db.session.commit()
    return len(DEFAULT_ASSET_TYPES)


def ensure_ceo_employee(user):
    if user.employee is not None:
        return False
    db.session.add(Employee(
        name=user.name, job_title="CEO", salary=0, phone=user.phone, email=user.email,
        start_date=date.today(), is_active=True, user_id=user.id,
    ))
    db.session.commit()
    return True


def main():
    app = create_app()
    with app.app_context():
        phone = os.getenv("CEO_PHONE", "255700000000")
        name = os.getenv("CEO_NAME")
        email = os.getenv("CEO_EMAIL")
        password = os.getenv("CEO_PASSWORD")

        if not name or not name.strip():
            raise SystemExit(
                "CEO_NAME is required to seed the CEO account — set it to the actual CEO's name, "
                "not a placeholder like 'System Admin'."
            )
        if not email or not email.strip():
            raise SystemExit("CEO_EMAIL is required to seed the CEO account — no fallback default exists any more.")
        if not password:
            raise SystemExit("CEO_PASSWORD is required to seed the CEO account — no fallback default exists any more.")
        try:
            validate_password_strength(password, field="CEO_PASSWORD")
        except ValueError as exc:
            raise SystemExit(str(exc))

        user = User.query.filter_by(phone=phone).first()
        if user is None:
            user = User.query.filter_by(role="ceo").first()  # phone changed but a CEO already exists

        if user is not None:
            if os.getenv("CEO_RESET_PASSWORD", "false").lower() == "true":
                user.set_password(password)
                user.must_change_password = True
                user.name = name.strip()
                user.email = email.strip()
                user.phone = phone
                user.role = "ceo"
                user.is_active = True
                user.email_verified = True
                user.deactivated_at = None
                db.session.commit()
                print(f"CEO password reset: {user.email}")
            else:
                print(f"CEO user already exists: {user.email}")
            created_employee = ensure_ceo_employee(user)
            created_types = ensure_asset_types()
            print(f"employee linked: {created_employee}, asset types seeded: {created_types}")
            return

        user = User(
            name=name.strip(),
            email=email.strip(),
            phone=phone,
            role="ceo",
            is_active=True,
            email_verified=True,
            must_change_password=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        ensure_ceo_employee(user)
        created_types = ensure_asset_types()

        print("CEO user created")
        print(f"Email: {user.email}")
        print(f"Phone: {phone}")
        print(f"Asset types seeded: {created_types}")
        print("The CEO must set a new password on first login (must_change_password).")


if __name__ == "__main__":
    main()
