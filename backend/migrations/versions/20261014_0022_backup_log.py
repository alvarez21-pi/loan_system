"""Phase 6: backup_logs table — one row per backup actually produced
(an interactive encrypted download, or the unattended nightly copy).

Revision ID: 20261014_0022
Revises: 20261013_0021
"""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0022"
down_revision = "20261013_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backup_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_name_snapshot", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_backup_logs_user_id", "backup_logs", ["user_id"])
    op.create_index("ix_backup_logs_created_at", "backup_logs", ["created_at"])


def downgrade():
    op.drop_index("ix_backup_logs_created_at", table_name="backup_logs")
    op.drop_index("ix_backup_logs_user_id", table_name="backup_logs")
    op.drop_table("backup_logs")
