"""The Settings page is removed entirely — address/phone/email and the
default instalment-rounding step are no longer editable from the UI or
stored in the database; they now live in backend/branding.py with their
current values as fixed defaults. Drops the now-empty company_settings
table.

Revision ID: 20261017_0025
Revises: 20261016_0024
"""
from alembic import op
import sqlalchemy as sa

revision = "20261017_0025"
down_revision = "20261016_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("company_settings")


def downgrade():
    op.create_table(
        "company_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("instalment_rounding_step", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
