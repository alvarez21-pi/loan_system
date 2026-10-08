"""Phase 2 item 4: optimistic-lock version columns on loans, penalties,
leave_requests and payroll_batches, backing the SELECT ... FOR UPDATE +
version-check guard against double-applying a concurrent approve/reject/
finalize/repayment.

Revision ID: 20261011_0016
Revises: 20261010_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0016"
down_revision = "20261010_0015"
branch_labels = None
depends_on = None

TABLES = ("loans", "penalties", "leave_requests", "payroll_batches")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    for table in TABLES:
        op.drop_column(table, "lock_version")
