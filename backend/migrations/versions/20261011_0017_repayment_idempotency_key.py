"""Phase 2 item 5: repayments.idempotency_key, unique, so a retried/
double-fired submission of the repayment or settle form can never record
the same payment twice.

Revision ID: 20261011_0017
Revises: 20261011_0016
"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0017"
down_revision = "20261011_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("repayments", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_repayments_idempotency_key", "repayments", ["idempotency_key"])


def downgrade():
    op.drop_constraint("uq_repayments_idempotency_key", "repayments", type_="unique")
    op.drop_column("repayments", "idempotency_key")
