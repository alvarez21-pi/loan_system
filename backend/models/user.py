from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from services.permissions import role_label


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="maker")
    # Null for the two unscoped tiers (ceo, head_manager); required for the
    # three scoped ones (department_manager, checker, maker) — see Part 1.
    department = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    # Bumped every time a setup/reset token is actually consumed (password
    # set). Embedded in every issued token (services.accounts.reset_token) so
    # a token stops validating the instant ANY outstanding link for this user
    # is used — single-use enforcement without a separate revocation table
    # (Part 2: the set-password page must treat a used token as invalid).
    credentials_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # Phase 2 item 3: forces a password change on next login — set True when
    # the CEO account is first seeded (or its password reset by the seed
    # script), cleared the moment POST /api/auth/change-password succeeds.
    # auth_required() blocks every OTHER endpoint while this is True.
    must_change_password = db.Column(db.Boolean, nullable=False, default=False, server_default="false")

    __table_args__ = (
        db.CheckConstraint(
            "role IN ('ceo', 'head_manager', 'department_manager', 'checker', 'maker')",
            name="ck_users_role",
        ),
        db.CheckConstraint(
            "(role IN ('ceo', 'head_manager') AND department IS NULL) OR "
            "(role IN ('department_manager', 'checker', 'maker') AND department IS NOT NULL)",
            name="ck_users_department_scope",
        ),
        db.CheckConstraint(
            "department IN ('hr', 'finance', 'loans_credit', 'general') OR department IS NULL",
            name="ck_users_department_value",
        ),
    )

    @property
    def display_role(self):
        """The title shown in the UI — a department_manager is always shown
        by its derived title ("HR Manager" etc.), never the raw pair (Part 3)."""
        return role_label(self.role, self.department)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def deactivate(self):
        self.is_active = False
        self.deactivated_at = datetime.utcnow()

    def reactivate(self):
        self.is_active = True
        self.deactivated_at = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "department": self.department,
            "display_role": self.display_role,
            "is_active": self.is_active,
            "email_verified": self.email_verified,
            "must_change_password": self.must_change_password,
            "deactivated_at": self.deactivated_at.isoformat() if self.deactivated_at else None,
            "employee_id": self.employee.id if getattr(self, "employee", None) else None,
            "employee_name": self.employee.name if getattr(self, "employee", None) else None,
        }
