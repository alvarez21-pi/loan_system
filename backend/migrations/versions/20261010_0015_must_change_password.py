"""Phase 2 item 3: users.must_change_password.

Revision ID: 20261010_0015
Revises: 20261006_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0015"
down_revision = "20261006_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "must_change_password")
