"""permission matrix, self-approval, expense/payroll workflow change, capital
entry types, asset types, company settings, borrower identity rework

Revision ID: 20260928_0008
Revises: 20260926_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0008"
down_revision = "20260926_0007"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "borrowers:view", "borrowers:manage",
    "loans:view", "loans:create", "loans:approve",
    "penalties:view", "penalties:create", "penalties:approve",
    "repayments:record",
    "calculator:use",
    "reports:view", "reports:financial",
    "capital:view", "capital:manage",
    "assets:manage",
    "expenses:manage",
    "employees:manage",
    "payroll:manage",
    "leave:request", "leave:manage",
    "users:manage",
    "audit:view",
    "settings:manage",
)

ROLE_TEMPLATES = {
    "manager": PERMISSIONS,
    "maker": (
        "borrowers:view", "borrowers:manage", "loans:view", "loans:create",
        "penalties:view", "penalties:create", "repayments:record", "calculator:use", "leave:request",
    ),
    "checker": (
        "borrowers:view", "loans:view", "loans:approve", "penalties:view",
        "penalties:approve", "reports:view", "leave:request",
    ),
}

DEFAULT_ASSET_TYPES = (
    "Land", "Building", "Vehicle", "Motorcycle", "Furniture & Fittings",
    "Computers & Electronics", "Office Equipment", "Machinery", "Other",
)


def upgrade():
    bind = op.get_bind()

    # ---------------------------------------------------------- permissions
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "permission", name="uq_user_permissions_user_permission"),
    )
    op.create_index(op.f("ix_user_permissions_user_id"), "user_permissions", ["user_id"])
    # CEO is never stored (always everything); manager/checker/maker get their
    # role template as a starting point — an operator narrows from there.
    for role, perms in ROLE_TEMPLATES.items():
        for permission in perms:
            op.execute(
                sa.text(
                    "INSERT INTO user_permissions (user_id, permission) "
                    "SELECT id, :permission FROM users WHERE role = :role"
                ).bindparams(permission=permission, role=role)
            )
    op.drop_index("ix_approval_scopes_user_id", table_name="approval_scopes")
    op.drop_table("approval_scopes")

    # -------------------------------------------------- self-approval flags
    op.add_column("loans", sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("penalties", sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.false()))

    # ------------------------------------------------- expenses: no approval
    op.drop_constraint("expenses_approved_by_fkey", "expenses", type_="foreignkey")
    op.drop_column("expenses", "approved_by")
    op.drop_column("expenses", "approver_name_snapshot")
    op.drop_column("expenses", "rejection_reason")
    op.drop_constraint("ck_expenses_status", "expenses", type_="check")
    op.execute("UPDATE expenses SET status = 'recorded'")
    op.create_check_constraint(
        "ck_expenses_status", "expenses",
        "status IN ('recorded', 'pending', 'approved', 'rejected')",
    )

    # --------------------------------------- payroll: single-action finalize
    op.drop_constraint("ck_payroll_batches_status", "payroll_batches", type_="check")
    op.execute("UPDATE payroll_batches SET status = 'draft' WHERE status = 'pending'")
    op.execute("UPDATE payroll_batches SET status = 'paid' WHERE status = 'approved'")
    op.execute("UPDATE payroll_batches SET status = 'cancelled' WHERE status = 'rejected'")
    op.create_check_constraint(
        "ck_payroll_batches_status", "payroll_batches", "status IN ('draft', 'paid', 'cancelled')",
    )
    op.alter_column("payroll_batches", "approved_by", new_column_name="finalized_by")
    op.alter_column("payroll_batches", "approver_name_snapshot", new_column_name="finalizer_name_snapshot")
    op.add_column("payroll_batches", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE payroll_batches SET finalized_at = created_at WHERE status = 'paid'")
    op.drop_column("payroll_batches", "rejection_reason")

    op.drop_constraint("ck_payroll_runs_status", "payroll_runs", type_="check")
    op.execute("UPDATE payroll_runs SET status = 'paid' WHERE status = 'approved'")
    op.execute("UPDATE payroll_runs SET status = 'draft' WHERE status = 'pending'")
    op.create_check_constraint("ck_payroll_runs_status", "payroll_runs", "status IN ('draft', 'paid')")
    op.drop_constraint("payroll_runs_approved_by_fkey", "payroll_runs", type_="foreignkey")
    op.drop_column("payroll_runs", "approved_by")
    op.drop_column("payroll_runs", "approver_name_snapshot")

    # ------------------------------------------------------------ assets
    op.create_table(
        "asset_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_asset_types_name"),
    )
    for name in DEFAULT_ASSET_TYPES:
        op.execute(sa.text("INSERT INTO asset_types (name) VALUES (:name)").bindparams(name=name))
    # Any distinct free-text type already in use that isn't a default gets its own row too.
    op.execute(
        "INSERT INTO asset_types (name) "
        "SELECT DISTINCT type FROM assets WHERE type IS NOT NULL "
        "AND type NOT IN (SELECT name FROM asset_types) "
        "ON CONFLICT DO NOTHING"
    )
    op.add_column("assets", sa.Column("asset_type_id", sa.Integer(), nullable=True))
    op.create_foreign_key("assets_asset_type_id_fkey", "assets", "asset_types", ["asset_type_id"], ["id"])
    op.execute("UPDATE assets SET asset_type_id = asset_types.id FROM asset_types WHERE asset_types.name = assets.type")

    # ------------------------------------------------------------ capital
    op.add_column("capital_entries", sa.Column("entry_type", sa.String(length=20), nullable=False, server_default="opening"))
    op.add_column("capital_entries", sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("capital_entries", sa.Column("date", sa.Date(), nullable=True))
    op.add_column("capital_entries", sa.Column("note", sa.Text(), nullable=True))
    op.alter_column("capital_entries", "reason", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "ck_capital_entries_type", "capital_entries", "entry_type IN ('opening', 'injection', 'withdrawal')",
    )

    # ------------------------------------------------------ company settings
    op.create_table(
        "company_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False, server_default="Microfinance LMS"),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("logo_path", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------ borrower identity
    op.add_column("borrowers", sa.Column("id_type", sa.String(length=20), nullable=False, server_default="nida"))
    op.add_column("borrowers", sa.Column("id_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("borrowers", sa.Column("id_verified_at", sa.DateTime(), nullable=True))
    op.add_column("borrowers", sa.Column("id_verification_source", sa.String(length=80), nullable=True))
    op.drop_index("ix_borrowers_nida_number", table_name="borrowers")
    op.drop_column("borrowers", "nida_number")
    op.drop_constraint("borrowers_id_number_key", "borrowers", type_="unique")
    op.drop_index("ix_borrowers_id_number", table_name="borrowers")
    op.create_index(op.f("ix_borrowers_id_number"), "borrowers", ["id_number"])
    op.create_unique_constraint("uq_borrowers_id_type_number", "borrowers", ["id_type", "id_number"])
    op.create_check_constraint(
        "ck_borrowers_id_type", "borrowers",
        "id_type IN ('nida', 'driving_licence', 'voter_id', 'passport', 'other')",
    )


def downgrade():
    op.drop_constraint("ck_borrowers_id_type", "borrowers", type_="check")
    op.drop_constraint("uq_borrowers_id_type_number", "borrowers", type_="unique")
    op.drop_index(op.f("ix_borrowers_id_number"), table_name="borrowers")
    op.create_index("ix_borrowers_id_number", "borrowers", ["id_number"], unique=True)
    op.create_unique_constraint("borrowers_id_number_key", "borrowers", ["id_number"])
    op.add_column("borrowers", sa.Column("nida_number", sa.String(length=30), nullable=True))
    op.create_index("ix_borrowers_nida_number", "borrowers", ["nida_number"], unique=True)
    op.drop_column("borrowers", "id_verification_source")
    op.drop_column("borrowers", "id_verified_at")
    op.drop_column("borrowers", "id_verified")
    op.drop_column("borrowers", "id_type")

    op.drop_table("company_settings")

    op.drop_constraint("ck_capital_entries_type", "capital_entries", type_="check")
    op.drop_column("capital_entries", "note")
    op.drop_column("capital_entries", "date")
    op.drop_column("capital_entries", "amount")
    op.drop_column("capital_entries", "entry_type")
    op.alter_column("capital_entries", "reason", existing_type=sa.Text(), nullable=False)

    op.execute("UPDATE assets SET asset_type_id = NULL")
    op.drop_constraint("assets_asset_type_id_fkey", "assets", type_="foreignkey")
    op.drop_column("assets", "asset_type_id")
    op.drop_table("asset_types")

    op.add_column("payroll_runs", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("payroll_runs", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.create_foreign_key("payroll_runs_approved_by_fkey", "payroll_runs", "users", ["approved_by"], ["id"], ondelete="SET NULL")
    op.drop_constraint("ck_payroll_runs_status", "payroll_runs", type_="check")
    op.execute("UPDATE payroll_runs SET status = 'approved' WHERE status = 'paid'")
    op.create_check_constraint("ck_payroll_runs_status", "payroll_runs", "status IN ('pending', 'approved', 'paid')")

    op.add_column("payroll_batches", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.drop_column("payroll_batches", "finalized_at")
    op.alter_column("payroll_batches", "finalizer_name_snapshot", new_column_name="approver_name_snapshot")
    op.alter_column("payroll_batches", "finalized_by", new_column_name="approved_by")
    op.drop_constraint("ck_payroll_batches_status", "payroll_batches", type_="check")
    op.execute("UPDATE payroll_batches SET status = 'approved' WHERE status = 'paid'")
    op.execute("UPDATE payroll_batches SET status = 'pending' WHERE status = 'draft'")
    op.execute("UPDATE payroll_batches SET status = 'rejected' WHERE status = 'cancelled'")
    op.create_check_constraint("ck_payroll_batches_status", "payroll_batches", "status IN ('pending', 'approved', 'rejected')")

    op.drop_constraint("ck_expenses_status", "expenses", type_="check")
    op.execute("UPDATE expenses SET status = 'approved' WHERE status = 'recorded'")
    op.create_check_constraint("ck_expenses_status", "expenses", "status IN ('pending', 'approved', 'rejected')")
    op.add_column("expenses", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("expenses", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("expenses", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.create_foreign_key("expenses_approved_by_fkey", "expenses", "users", ["approved_by"], ["id"], ondelete="SET NULL")

    op.drop_column("penalties", "self_approved")
    op.drop_column("loans", "self_approved")

    op.create_table(
        "approval_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope", name="uq_approval_scopes_user_scope"),
        sa.CheckConstraint(
            "scope IN ('loans', 'penalties', 'expenses', 'payroll', 'leave_requests')",
            name="ck_approval_scopes_scope",
        ),
    )
    op.create_index("ix_approval_scopes_user_id", "approval_scopes", ["user_id"])
    op.drop_index(op.f("ix_user_permissions_user_id"), table_name="user_permissions")
    op.drop_table("user_permissions")
