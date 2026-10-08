"""Part 8/9 schema support:
- loans.decided_at / penalties.decided_at / leave_requests.decided_at: set
  the moment an approve/reject decision is made, so a stale second approver
  can be told exactly who beat them to it and when, instead of a generic
  "already decided" error.
- leave_requests.original_start_date / original_end_date: preserves what was
  originally requested when an approver edits the dates before approving
  (Part 9.2).

Revision ID: 20261004_0012
Revises: 20261003_0011
"""
from alembic import op
import sqlalchemy as sa

revision = "20261004_0012"
down_revision = "20261003_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("loans", sa.Column("decided_at", sa.DateTime(), nullable=True))
    op.add_column("penalties", sa.Column("decided_at", sa.DateTime(), nullable=True))
    op.add_column("leave_requests", sa.Column("decided_at", sa.DateTime(), nullable=True))
    op.add_column("leave_requests", sa.Column("original_start_date", sa.Date(), nullable=True))
    op.add_column("leave_requests", sa.Column("original_end_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("leave_requests", "original_end_date")
    op.drop_column("leave_requests", "original_start_date")
    op.drop_column("leave_requests", "decided_at")
    op.drop_column("penalties", "decided_at")
    op.drop_column("loans", "decided_at")
