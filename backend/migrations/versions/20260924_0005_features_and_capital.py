"""borrower NIDA number, employee job_title/user link, penalty reversal, opening capital ledger

Revision ID: 20260924_0005
Revises: 20260922_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20260924_0005"
down_revision = "20260922_0004"
branch_labels = None
depends_on = None


def upgrade():
    # --- borrowers: NIDA number (Tanzanian national ID), separate from photo_url ---
    op.add_column("borrowers", sa.Column("nida_number", sa.String(length=30), nullable=True))
    op.create_index(op.f("ix_borrowers_nida_number"), "borrowers", ["nida_number"], unique=True)

    # --- employees: job_title (descriptive only) + optional link to a User account ---
    op.alter_column("employees", "role", new_column_name="job_title")
    op.add_column("employees", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_employees_user_id", "employees", ["user_id"])
    op.create_foreign_key(
        "employees_user_id_fkey", "employees", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    # --- penalties: reversal fields, 'reversed' status ---
    op.add_column("penalties", sa.Column("reversed_at", sa.DateTime(), nullable=True))
    op.add_column("penalties", sa.Column("reversed_by", sa.Integer(), nullable=True))
    op.add_column("penalties", sa.Column("reversed_by_name_snapshot", sa.String(length=120), nullable=True))
    op.add_column("penalties", sa.Column("reversal_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "penalties_reversed_by_fkey", "penalties", "users", ["reversed_by"], ["id"], ondelete="SET NULL"
    )
    op.drop_constraint("ck_penalties_status", "penalties", type_="check")
    op.create_check_constraint(
        "ck_penalties_status",
        "penalties",
        "status IN ('pending', 'approved', 'rejected', 'reversed')",
    )

    # --- opening capital ledger ---
    op.create_table(
        "capital_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("previous_value", sa.Numeric(15, 2), nullable=False),
        sa.Column("new_value", sa.Numeric(15, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_by_name_snapshot", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("capital_entries")

    op.drop_constraint("ck_penalties_status", "penalties", type_="check")
    op.create_check_constraint(
        "ck_penalties_status", "penalties", "status IN ('pending', 'approved', 'rejected')"
    )
    op.drop_constraint("penalties_reversed_by_fkey", "penalties", type_="foreignkey")
    op.drop_column("penalties", "reversal_reason")
    op.drop_column("penalties", "reversed_by_name_snapshot")
    op.drop_column("penalties", "reversed_by")
    op.drop_column("penalties", "reversed_at")

    op.drop_constraint("employees_user_id_fkey", "employees", type_="foreignkey")
    op.drop_constraint("uq_employees_user_id", "employees", type_="unique")
    op.drop_column("employees", "user_id")
    op.alter_column("employees", "job_title", new_column_name="role")

    op.drop_index(op.f("ix_borrowers_nida_number"), table_name="borrowers")
    op.drop_column("borrowers", "nida_number")
