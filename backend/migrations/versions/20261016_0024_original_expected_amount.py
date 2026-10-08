"""A partially-paid instalment row needs to keep showing what was
originally due, even after its own expected_amount has been reduced to
the residual still owed, so the shortfall is visible on screen —
payment_schedules gains original_expected_amount, backfilled from the
current expected_amount for existing rows (the best available value for
a row that has never been touched; one that HAS already been partially
paid loses the true original figure, same limitation original_due_date
would have on a column added after the fact).

Revision ID: 20261016_0024
Revises: 20261015_0023
"""
from alembic import op
import sqlalchemy as sa

revision = "20261016_0024"
down_revision = "20261015_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_schedules", sa.Column("original_expected_amount", sa.Numeric(15, 2), nullable=True))
    op.execute("UPDATE payment_schedules SET original_expected_amount = expected_amount")


def downgrade():
    op.drop_column("payment_schedules", "original_expected_amount")
