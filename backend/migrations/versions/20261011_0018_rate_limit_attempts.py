"""Phase 2 item 7: rate_limit_attempts — a DB-backed counter so login/
forgot-password/resend-verification/verify/set-password rate limiting
works across every gunicorn worker process, not an in-memory counter local
to one.

Revision ID: 20261011_0018
Revises: 20261011_0017
"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0018"
down_revision = "20261011_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("scope", "identifier", name="uq_rate_limit_scope_identifier"),
    )


def downgrade():
    op.drop_table("rate_limit_attempts")
