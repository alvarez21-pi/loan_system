"""ceo/manager role structure, user deletion lifecycle, and audit/name snapshots

Revision ID: 20260922_0004
Revises: 20260921_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0004"
down_revision = "20260921_0003"
branch_labels = None
depends_on = None


def upgrade():
    # --- roles: admin -> ceo, and widen the allowed role set ---
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'ceo' WHERE role = 'admin'")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('ceo', 'manager', 'checker', 'maker')",
    )
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(), nullable=True))

    # --- audit_logs: actor snapshot + nullable, non-cascading user FK ---
    op.add_column("audit_logs", sa.Column("actor_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_email_snapshot", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE audit_logs SET actor_name_snapshot = users.name, actor_email_snapshot = users.email "
        "FROM users WHERE users.id = audit_logs.user_id"
    )
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.alter_column("audit_logs", "user_id", nullable=True)
    op.create_foreign_key(
        "audit_logs_user_id_fkey", "audit_logs", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    # --- loans: creator/approver name snapshots + non-cascading FKs ---
    op.add_column("loans", sa.Column("creator_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("loans", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE loans SET creator_name_snapshot = users.name FROM users WHERE users.id = loans.created_by"
    )
    op.execute(
        "UPDATE loans SET approver_name_snapshot = users.name FROM users WHERE users.id = loans.approved_by"
    )
    op.drop_constraint("loans_created_by_fkey", "loans", type_="foreignkey")
    op.drop_constraint("loans_approved_by_fkey", "loans", type_="foreignkey")
    op.alter_column("loans", "created_by", nullable=True)
    op.create_foreign_key(
        "loans_created_by_fkey", "loans", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "loans_approved_by_fkey", "loans", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )

    # --- penalties: added_by/approver name snapshots + non-cascading FKs ---
    op.add_column("penalties", sa.Column("added_by_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("penalties", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE penalties SET added_by_name_snapshot = users.name FROM users WHERE users.id = penalties.added_by"
    )
    op.execute(
        "UPDATE penalties SET approver_name_snapshot = users.name FROM users WHERE users.id = penalties.approved_by"
    )
    op.drop_constraint("penalties_added_by_fkey", "penalties", type_="foreignkey")
    op.drop_constraint("penalties_approved_by_fkey", "penalties", type_="foreignkey")
    op.alter_column("penalties", "added_by", nullable=True)
    op.create_foreign_key(
        "penalties_added_by_fkey", "penalties", "users", ["added_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "penalties_approved_by_fkey", "penalties", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )

    # --- expenses: added_by/approver name snapshots + non-cascading FKs ---
    op.add_column("expenses", sa.Column("added_by_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("expenses", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE expenses SET added_by_name_snapshot = users.name FROM users WHERE users.id = expenses.added_by"
    )
    op.execute(
        "UPDATE expenses SET approver_name_snapshot = users.name FROM users WHERE users.id = expenses.approved_by"
    )
    op.drop_constraint("expenses_added_by_fkey", "expenses", type_="foreignkey")
    op.drop_constraint("expenses_approved_by_fkey", "expenses", type_="foreignkey")
    op.alter_column("expenses", "added_by", nullable=True)
    op.create_foreign_key(
        "expenses_added_by_fkey", "expenses", "users", ["added_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "expenses_approved_by_fkey", "expenses", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )

    # --- payroll_runs: creator/approver name snapshots + non-cascading FKs ---
    op.add_column("payroll_runs", sa.Column("creator_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("payroll_runs", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE payroll_runs SET creator_name_snapshot = users.name FROM users WHERE users.id = payroll_runs.created_by"
    )
    op.execute(
        "UPDATE payroll_runs SET approver_name_snapshot = users.name FROM users WHERE users.id = payroll_runs.approved_by"
    )
    op.drop_constraint("payroll_runs_created_by_fkey", "payroll_runs", type_="foreignkey")
    op.drop_constraint("payroll_runs_approved_by_fkey", "payroll_runs", type_="foreignkey")
    op.alter_column("payroll_runs", "created_by", nullable=True)
    op.create_foreign_key(
        "payroll_runs_created_by_fkey", "payroll_runs", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "payroll_runs_approved_by_fkey", "payroll_runs", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )

    # --- leave_requests: add approved_by, creator/approver name snapshots, non-cascading FKs ---
    op.add_column("leave_requests", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("leave_requests", sa.Column("creator_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("leave_requests", sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE leave_requests SET creator_name_snapshot = users.name FROM users WHERE users.id = leave_requests.created_by"
    )
    op.drop_constraint("fk_leave_requests_created_by", "leave_requests", type_="foreignkey")
    op.alter_column("leave_requests", "created_by", nullable=True)
    op.create_foreign_key(
        "fk_leave_requests_created_by", "leave_requests", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_leave_requests_approved_by", "leave_requests", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )


def downgrade():
    op.drop_constraint("fk_leave_requests_approved_by", "leave_requests", type_="foreignkey")
    op.drop_constraint("fk_leave_requests_created_by", "leave_requests", type_="foreignkey")
    op.alter_column("leave_requests", "created_by", nullable=False)
    op.create_foreign_key("fk_leave_requests_created_by", "leave_requests", "users", ["created_by"], ["id"])
    op.drop_column("leave_requests", "approver_name_snapshot")
    op.drop_column("leave_requests", "creator_name_snapshot")
    op.drop_column("leave_requests", "approved_by")

    op.drop_constraint("payroll_runs_approved_by_fkey", "payroll_runs", type_="foreignkey")
    op.drop_constraint("payroll_runs_created_by_fkey", "payroll_runs", type_="foreignkey")
    op.alter_column("payroll_runs", "created_by", nullable=False)
    op.create_foreign_key("payroll_runs_created_by_fkey", "payroll_runs", "users", ["created_by"], ["id"])
    op.create_foreign_key("payroll_runs_approved_by_fkey", "payroll_runs", "users", ["approved_by"], ["id"])
    op.drop_column("payroll_runs", "approver_name_snapshot")
    op.drop_column("payroll_runs", "creator_name_snapshot")

    op.drop_constraint("expenses_approved_by_fkey", "expenses", type_="foreignkey")
    op.drop_constraint("expenses_added_by_fkey", "expenses", type_="foreignkey")
    op.alter_column("expenses", "added_by", nullable=False)
    op.create_foreign_key("expenses_added_by_fkey", "expenses", "users", ["added_by"], ["id"])
    op.create_foreign_key("expenses_approved_by_fkey", "expenses", "users", ["approved_by"], ["id"])
    op.drop_column("expenses", "approver_name_snapshot")
    op.drop_column("expenses", "added_by_name_snapshot")

    op.drop_constraint("penalties_approved_by_fkey", "penalties", type_="foreignkey")
    op.drop_constraint("penalties_added_by_fkey", "penalties", type_="foreignkey")
    op.alter_column("penalties", "added_by", nullable=False)
    op.create_foreign_key("penalties_added_by_fkey", "penalties", "users", ["added_by"], ["id"])
    op.create_foreign_key("penalties_approved_by_fkey", "penalties", "users", ["approved_by"], ["id"])
    op.drop_column("penalties", "approver_name_snapshot")
    op.drop_column("penalties", "added_by_name_snapshot")

    op.drop_constraint("loans_approved_by_fkey", "loans", type_="foreignkey")
    op.drop_constraint("loans_created_by_fkey", "loans", type_="foreignkey")
    op.alter_column("loans", "created_by", nullable=False)
    op.create_foreign_key("loans_created_by_fkey", "loans", "users", ["created_by"], ["id"])
    op.create_foreign_key("loans_approved_by_fkey", "loans", "users", ["approved_by"], ["id"])
    op.drop_column("loans", "approver_name_snapshot")
    op.drop_column("loans", "creator_name_snapshot")

    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.alter_column("audit_logs", "user_id", nullable=False)
    op.create_foreign_key("audit_logs_user_id_fkey", "audit_logs", "users", ["user_id"], ["id"])
    op.drop_column("audit_logs", "actor_email_snapshot")
    op.drop_column("audit_logs", "actor_name_snapshot")

    op.drop_column("users", "deactivated_at")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'ceo'")
    op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'maker', 'checker')")
