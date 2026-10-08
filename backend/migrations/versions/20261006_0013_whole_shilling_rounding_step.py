"""Part 1 (whole shillings, rounded up): the instalment-rounding step.

- loans.rounding_step: copied from the company default AT CREATION TIME and
  used for every later recalculation on that loan - changing the company
  default never alters an existing loan.
- company_settings.instalment_rounding_step: the default step for a NEW
  loan (CEO/Head Manager editable), defaults to 1,000.

Revision ID: 20261006_0013
Revises: 20261004_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0013"
down_revision = "20261004_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("loans", sa.Column("rounding_step", sa.Integer(), nullable=False, server_default="1000"))
    op.add_column("company_settings", sa.Column("instalment_rounding_step", sa.Integer(), nullable=False, server_default="1000"))


def downgrade():
    op.drop_column("company_settings", "instalment_rounding_step")
    op.drop_column("loans", "rounding_step")
