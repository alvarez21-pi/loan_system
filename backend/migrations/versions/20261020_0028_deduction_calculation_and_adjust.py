"""Fixed-vs-percentage is now chosen per EmployeeDeduction assignment
(independent of the DeductionType), so employee_deductions gains
calculation/rate and amount becomes optional (unused for a percentage
assignment). payroll_deduction_lines gains is_adjusted, for a per-run-only
edit that never touches the standing deduction/assignment. Seeds the four
individual-scope deduction types the Employee page's "Add deduction" form
expects to already exist (idempotent — skipped if already present, e.g.
re-run or already created by hand).

Revision ID: 20261020_0028
Revises: 20261019_0027
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_0028"
down_revision = "20261019_0027"
branch_labels = None
depends_on = None

SEED_TYPES = ["Loan Repayment", "Salary Advance", "Uniform", "Other"]


def upgrade():
    op.add_column("employee_deductions", sa.Column("calculation", sa.String(length=10), nullable=False, server_default="fixed"))
    op.add_column("employee_deductions", sa.Column("rate", sa.Numeric(7, 4), nullable=True))
    op.alter_column("employee_deductions", "amount", nullable=True)
    op.create_check_constraint("ck_employee_deductions_calculation", "employee_deductions", "calculation IN ('fixed', 'percentage')")

    op.add_column("payroll_deduction_lines", sa.Column("is_adjusted", sa.Boolean(), nullable=False, server_default="false"))

    conn = op.get_bind()
    deduction_types = sa.table(
        "deduction_types",
        sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("calculation", sa.String),
        sa.column("side", sa.String), sa.column("scope", sa.String), sa.column("is_active", sa.Boolean),
        sa.column("fixed_amount", sa.Numeric),
    )
    existing = {row[0] for row in conn.execute(sa.text("SELECT name FROM deduction_types"))}
    for name in SEED_TYPES:
        if name not in existing:
            conn.execute(deduction_types.insert().values(
                name=name, calculation="fixed", side="employee", scope="individual", is_active=True, fixed_amount=0,
            ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM deduction_types WHERE name IN :names AND scope = 'individual'").bindparams(
        sa.bindparam("names", expanding=True)
    ), {"names": SEED_TYPES})
    op.drop_column("payroll_deduction_lines", "is_adjusted")
    op.drop_constraint("ck_employee_deductions_calculation", "employee_deductions", type_="check")
    op.alter_column("employee_deductions", "amount", nullable=False)
    op.drop_column("employee_deductions", "rate")
    op.drop_column("employee_deductions", "calculation")
