"""Migration 20261006_0014 seeded "PAYE" with bands=[] on purpose (no rate
hardcoded until someone sets a real one) - but nobody had, so every
payslip's PAYE line is still silently 0 regardless of salary. Fills in
the current TRA resident-employment monthly PAYE bands (Income Tax Act,
as confirmed against the TRA table current as of this change) so payroll
is correct out of the box; still editable from the Deduction Types page
like any other deduction if a future Finance Act changes these figures.

Monthly bands (marginal, TZS):
  0 - 270,000        : 0%
  270,001 - 520,000   : 8%
  520,001 - 760,000   : 20%
  760,001 - 1,000,000 : 25%
  over 1,000,000      : 30%

Revision ID: 20261021_0029
Revises: 20261020_0028
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0029"
down_revision = "20261020_0028"
branch_labels = None
depends_on = None

CURRENT_BANDS = [
    {"up_to": 270000, "rate": 0},
    {"up_to": 520000, "rate": 8},
    {"up_to": 760000, "rate": 20},
    {"up_to": 1000000, "rate": 25},
    {"up_to": None, "rate": 30},
]
EMPTY_BANDS = []

deduction_types = sa.table(
    "deduction_types",
    sa.column("name", sa.String),
    sa.column("calculation", sa.String),
    sa.column("bands", sa.JSON),
)


def upgrade():
    conn = op.get_bind()
    conn.execute(
        deduction_types.update()
        .where(deduction_types.c.name == "PAYE")
        .where(deduction_types.c.calculation == "bands")
        .values(bands=CURRENT_BANDS)
    )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        deduction_types.update()
        .where(deduction_types.c.name == "PAYE")
        .where(deduction_types.c.calculation == "bands")
        .values(bands=EMPTY_BANDS)
    )
