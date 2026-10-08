"""Phase 3 items 1/2: payment_schedules gains original_due_date (set once,
backfilled from the existing due_date for every current row — none of
them have ever been delayed yet), delayed_months, and
paid_less_than_scheduled.

Revision ID: 20261012_0020
Revises: 20261011_0019
"""
from alembic import op
import sqlalchemy as sa

revision = "20261012_0020"
down_revision = "20261011_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_schedules", sa.Column("original_due_date", sa.Date(), nullable=True))
    op.execute("UPDATE payment_schedules SET original_due_date = due_date")
    op.add_column("payment_schedules", sa.Column("delayed_months", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payment_schedules", sa.Column("paid_less_than_scheduled", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("payment_schedules", "paid_less_than_scheduled")
    op.drop_column("payment_schedules", "delayed_months")
    op.drop_column("payment_schedules", "original_due_date")
