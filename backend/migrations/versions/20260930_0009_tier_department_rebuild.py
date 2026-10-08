"""Tier + department role rebuild (final rebuild prompt).

Retires the per-user permission-matrix table entirely (Part 0): permissions
are now derived purely from role tier + department, computed in
services/permissions.py — nothing stored per user beyond those two columns.

- users.role: ceo/manager/checker/maker -> ceo/head_manager/department_manager/
  checker/maker. Existing 'manager' becomes 'head_manager' (it had unrestricted
  cross-department access, matching Head Manager, not a single department).
- users.department: new column (hr/finance/loans_credit/general), required
  for department_manager/checker/maker, null for ceo/head_manager. Existing
  checker/maker default to 'general', adjustable afterward.
- Drops user_permissions entirely — the old checkbox matrix and its backing
  table are retired.
- Drops loans.self_approved / penalties.self_approved — no self-approval
  badge or tracking of any kind under the new model (Part 2).

Revision ID: 20260930_0009
Revises: 20260928_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260930_0009"
down_revision = "20260928_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("department", sa.String(length=20), nullable=True))

    # The old constraint doesn't know 'head_manager'/'department_manager' —
    # drop it before rewriting role values below.
    op.drop_constraint("ck_users_role", "users", type_="check")

    op.execute("UPDATE users SET role = 'head_manager' WHERE role = 'manager'")
    op.execute("UPDATE users SET department = 'general' WHERE role IN ('checker', 'maker') AND department IS NULL")

    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('ceo', 'head_manager', 'department_manager', 'checker', 'maker')",
    )
    op.create_check_constraint(
        "ck_users_department_scope",
        "users",
        "(role IN ('ceo', 'head_manager') AND department IS NULL) OR "
        "(role IN ('department_manager', 'checker', 'maker') AND department IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_users_department_value",
        "users",
        "department IN ('hr', 'finance', 'loans_credit', 'general') OR department IS NULL",
    )

    # Part 0: the old per-user permission-matrix checkboxes and their table.
    op.drop_index(op.f("ix_user_permissions_user_id"), table_name="user_permissions")
    op.drop_table("user_permissions")

    # Part 2: no self-approval badge or tracking of any kind under the new model.
    op.drop_column("loans", "self_approved")
    op.drop_column("penalties", "self_approved")


def downgrade():
    op.add_column("loans", sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("penalties", sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "user_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=False),
        sa.UniqueConstraint("user_id", "permission", name="uq_user_permissions_user_permission"),
    )
    op.create_index(op.f("ix_user_permissions_user_id"), "user_permissions", ["user_id"])

    op.drop_constraint("ck_users_department_value", "users", type_="check")
    op.drop_constraint("ck_users_department_scope", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'manager' WHERE role = 'head_manager'")
    # A department_manager has no equivalent in the old 4-tier model — this
    # collapses it to 'manager' too (lossy, best-effort rollback path only).
    op.execute("UPDATE users SET role = 'manager' WHERE role = 'department_manager'")
    op.create_check_constraint("ck_users_role", "users", "role IN ('ceo', 'manager', 'checker', 'maker')")
    op.drop_column("users", "department")
