"""Add repayment frequency to loans.

Revision ID: 20261027_0032
Revises: 20261023_0031
"""
from alembic import op
import sqlalchemy as sa

revision = "20261027_0032"
down_revision = "20261023_0031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("loans", sa.Column("term_unit", sa.String(10), nullable=False, server_default="monthly"))
    op.create_check_constraint("ck_loans_term_unit", "loans", "term_unit IN ('daily', 'weekly', 'monthly')")


def downgrade():
    op.drop_constraint("ck_loans_term_unit", "loans", type_="check")
    op.drop_column("loans", "term_unit")
