"""Part 5.2: itemized, configurable payroll deductions.

- deduction_types: configurable deduction/contribution definitions (name,
  fixed/percentage/progressive-bands, employee/employer side, active flag).
  NO rate is seeded - placeholders only (PAYE, NSSF, health insurance, loan
  or advance repayment), each with a zero rate/amount until HR/Head
  Manager/CEO sets a real one.
- payroll_deduction_lines: one line per deduction per payroll run, snapshotted.
- payroll_runs.employer_cost: sum of employer-side lines, shown separately,
  never subtracted from net pay.

Revision ID: 20261006_0014
Revises: 20261006_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0014"
down_revision = "20261006_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_runs", sa.Column("employer_cost", sa.Numeric(15, 2), nullable=False, server_default="0"))

    op.create_table(
        "deduction_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("calculation", sa.String(20), nullable=False, server_default="fixed"),
        sa.Column("side", sa.String(10), nullable=False, server_default="employee"),
        sa.Column("rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("fixed_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("bands", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("calculation IN ('fixed', 'percentage', 'bands')", name="ck_deduction_types_calculation"),
        sa.CheckConstraint("side IN ('employee', 'employer')", name="ck_deduction_types_side"),
    )

    op.create_table(
        "payroll_deduction_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deduction_type_id", sa.Integer(), sa.ForeignKey("deduction_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name_snapshot", sa.String(80), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.CheckConstraint("side IN ('employee', 'employer')", name="ck_payroll_deduction_lines_side"),
    )

    deduction_types = sa.table(
        "deduction_types",
        sa.column("name", sa.String),
        sa.column("calculation", sa.String),
        sa.column("side", sa.String),
        sa.column("rate", sa.Numeric),
        sa.column("fixed_amount", sa.Numeric),
        sa.column("bands", sa.JSON),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        deduction_types,
        [
            {"name": "PAYE", "calculation": "bands", "side": "employee", "rate": None, "fixed_amount": None, "bands": [], "is_active": True},
            {"name": "NSSF", "calculation": "percentage", "side": "employee", "rate": 0, "fixed_amount": None, "bands": None, "is_active": True},
            {"name": "Health Insurance", "calculation": "percentage", "side": "employee", "rate": 0, "fixed_amount": None, "bands": None, "is_active": True},
            {"name": "Loan/Advance Repayment", "calculation": "fixed", "side": "employee", "rate": None, "fixed_amount": 0, "bands": None, "is_active": True},
        ],
    )


def downgrade():
    op.drop_table("payroll_deduction_lines")
    op.drop_table("deduction_types")
    op.drop_column("payroll_runs", "employer_cost")
