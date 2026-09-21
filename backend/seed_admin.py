import os

from app import create_app
from extensions import db
from models import User


def main():
    app = create_app()
    with app.app_context():
        phone = os.getenv("ADMIN_PHONE", "255700000000")
        password = os.getenv("ADMIN_PASSWORD", "admin12345")

        existing_user = User.query.filter_by(phone=phone).first()
        if existing_user:
            if os.getenv("ADMIN_RESET_PASSWORD", "false").lower() == "true":
                existing_user.set_password(password)
                existing_user.email = os.getenv("ADMIN_EMAIL", existing_user.email)
                existing_user.is_active = True
                existing_user.email_verified = True
                db.session.commit()
                print(f"Admin password reset: {phone}")
                return
            print(f"Admin user already exists: {phone}")
            return

        user = User(
            name=os.getenv("ADMIN_NAME", "System Admin"),
            email=os.getenv("ADMIN_EMAIL", "admin@example.com"),
            phone=phone,
            role="admin",
            is_active=True,
            email_verified=True,
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        print("Admin user created")
        print(f"Phone: {phone}")
        print(f"Password: {password}")


if __name__ == "__main__":
    main()
