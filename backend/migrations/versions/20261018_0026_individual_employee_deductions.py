"""Not every employee has the same deductions. deduction_types gains
`scope` ('standard' — applies to everyone automatically, the existing
behaviour, now the explicit default so existing rows keep working; or
'individual' — applies only via an explicit assignment). New
employee_deductions table holds those per-employee assignments (amount,
start month, and either an end month or a remaining balance that reduces
each run). payroll_deduction_lines gains employee_deduction_id so
finalizing a batch can find and decrement the right assignment's balance.

Revision ID: 20261018_0026
Revises: 20261017_0025
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_0026"
down_revision = "20261017_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deduction_types", sa.Column("scope", sa.String(length=10), nullable=False, server_default="standard"))
    op.create_check_constraint("ck_deduction_types_scope", "deduction_types", "scope IN ('standard', 'individual')")

    op.create_table(
        "employee_deductions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deduction_type_id", sa.Integer(), sa.ForeignKey("deduction_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("start_month", sa.String(length=7), nullable=False),
        sa.Column("end_month", sa.String(length=7), nullable=True),
        sa.Column("remaining_balance", sa.Numeric(15, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_employee_deductions_employee_id", "employee_deductions", ["employee_id"])

    op.add_column(
        "payroll_deduction_lines",
        sa.Column("employee_deduction_id", sa.Integer(), sa.ForeignKey("employee_deductions.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade():
    op.drop_column("payroll_deduction_lines", "employee_deduction_id")
    op.drop_index("ix_employee_deductions_employee_id", table_name="employee_deductions")
    op.drop_table("employee_deductions")
    op.drop_constraint("ck_deduction_types_scope", "deduction_types", type_="check")
    op.drop_column("deduction_types", "scope")
