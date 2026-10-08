"""Phase 4: company_settings gains primary_color, accent_color and
footer_text, so every PDF/Excel/email surface can read branding colours
and a confidentiality line from the one settings record instead of a
hardcoded constant.

Revision ID: 20261013_0021
Revises: 20261012_0020
"""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0021"
down_revision = "20261012_0020"
branch_labels = None
depends_on = None

DEFAULT_PRIMARY_COLOR = "#1A3A5C"
DEFAULT_ACCENT_COLOR = "#2E75B6"
DEFAULT_FOOTER_TEXT = "This document is confidential and intended solely for the addressee."


def upgrade():
    op.add_column("company_settings", sa.Column("primary_color", sa.String(length=7), nullable=False, server_default=DEFAULT_PRIMARY_COLOR))
    op.add_column("company_settings", sa.Column("accent_color", sa.String(length=7), nullable=False, server_default=DEFAULT_ACCENT_COLOR))
    op.add_column("company_settings", sa.Column("footer_text", sa.Text(), nullable=False, server_default=DEFAULT_FOOTER_TEXT))


def downgrade():
    op.drop_column("company_settings", "footer_text")
    op.drop_column("company_settings", "accent_color")
    op.drop_column("company_settings", "primary_color")
