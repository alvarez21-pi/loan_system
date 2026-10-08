"""Branding (name, logo, colours, footer text) is no longer stored in the
database or editable from Settings — it now lives in two static config
files (backend/branding.py, frontend/src/branding.ts) so a different
client only ever means editing those two files and swapping the logo
asset, never a database migration. company_settings keeps the fields that
are genuine per-deployment operational settings: address, phone, email
(the company's own contact details — still editable) and
instalment_rounding_step.

Revision ID: 20261015_0023
Revises: 20261014_0022
"""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0023"
down_revision = "20261014_0022"
branch_labels = None
depends_on = None

DEFAULT_COMPANY_NAME = "Microfinance LMS"
DEFAULT_PRIMARY_COLOR = "#1A3A5C"
DEFAULT_ACCENT_COLOR = "#2E75B6"
DEFAULT_FOOTER_TEXT = "This document is confidential and intended solely for the addressee."


def upgrade():
    op.drop_column("company_settings", "footer_text")
    op.drop_column("company_settings", "accent_color")
    op.drop_column("company_settings", "primary_color")
    op.drop_column("company_settings", "logo_path")
    op.drop_column("company_settings", "name")


def downgrade():
    op.add_column("company_settings", sa.Column("name", sa.String(length=160), nullable=False, server_default=DEFAULT_COMPANY_NAME))
    op.add_column("company_settings", sa.Column("logo_path", sa.String(length=255), nullable=True))
    op.add_column("company_settings", sa.Column("primary_color", sa.String(length=7), nullable=False, server_default=DEFAULT_PRIMARY_COLOR))
    op.add_column("company_settings", sa.Column("accent_color", sa.String(length=7), nullable=False, server_default=DEFAULT_ACCENT_COLOR))
    op.add_column("company_settings", sa.Column("footer_text", sa.Text(), nullable=False, server_default=DEFAULT_FOOTER_TEXT))
