"""require user emails and track verification

Revision ID: 20260921_0003
Revises: 20260919_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0003"
down_revision = "20260919_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET email_verified = true WHERE email IS NOT NULL")
    op.alter_column("users", "email", nullable=False)
    op.alter_column("users", "email_verified", server_default=None)


def downgrade():
    op.drop_column("users", "email_verified")
    op.alter_column("users", "email", nullable=True)