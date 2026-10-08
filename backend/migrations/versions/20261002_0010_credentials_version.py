"""Single-use setup/reset tokens (Part 2).

Adds users.credentials_version, embedded in every issued setup/reset token
and bumped whenever one is actually consumed — so a used (or superseded)
token stops validating immediately, without a separate revocation table.

Revision ID: 20261002_0010
Revises: 20260930_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20261002_0010"
down_revision = "20260930_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("credentials_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("users", "credentials_version")
