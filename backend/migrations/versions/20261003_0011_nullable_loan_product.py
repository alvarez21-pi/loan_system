"""Negotiated/custom loans and locked product terms (Part 4.2/4.3):
- loans.loan_product_id becomes nullable so a Maker can create a loan
  without picking a product, entering principal/rate/term directly — it
  still runs through the exact same loan_calculator.py function either way.
- loan_products.default_term_months is added: when a product IS selected,
  both its rate and its term are locked (server-side, not just visually).
  Existing products backfill to 12 months.

Revision ID: 20261003_0011
Revises: 20261002_0010
"""
from alembic import op
import sqlalchemy as sa

revision = "20261003_0011"
down_revision = "20261002_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("loans", "loan_product_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "loan_products",
        sa.Column("default_term_months", sa.Integer(), nullable=False, server_default="12"),
    )


def downgrade():
    op.drop_column("loan_products", "default_term_months")
    # Any existing negotiated (product-less) loan has no sensible product to
    # backfill — this downgrade only works on a database with none.
    op.alter_column("loans", "loan_product_id", existing_type=sa.Integer(), nullable=False)
