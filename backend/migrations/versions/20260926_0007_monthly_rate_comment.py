"""Document interest_rate columns as MONTHLY rates (comment only, no data change).

Revision ID: 20260926_0007
Revises: 20260925_0006
"""
import sqlalchemy as sa
from alembic import op

revision = "20260926_0007"
down_revision = "20260925_0006"
branch_labels = None
depends_on = None

COMMENT = "Monthly interest rate in percent (10 = 10% per month)"


def upgrade():
    for table, column in (("loans", "interest_rate"), ("loan_products", "default_interest_rate")):
        op.alter_column(table, column, existing_type=sa.Numeric(5, 2), existing_nullable=False, comment=COMMENT)


def downgrade():
    for table, column in (("loans", "interest_rate"), ("loan_products", "default_interest_rate")):
        op.alter_column(table, column, existing_type=sa.Numeric(5, 2), existing_nullable=False, comment=None)
