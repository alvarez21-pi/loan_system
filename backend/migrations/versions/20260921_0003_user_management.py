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
    # Phase 2 item 10 (F-10): email was nullable from the initial schema
    # (0001) onward, so a database with any pre-existing user row created
    # before this migration — a demo/seed database, or any real deployment
    # upgraded from an early revision — can have NULL emails here. Without
    # this backfill, the NOT NULL below fails outright on such a database
    # ("column contains null values"). Each backfilled value is unique
    # (keyed by id) and obviously synthetic, never collides with a real
    # email, and is immediately visible to an admin as needing a real one.
    op.execute("UPDATE users SET email = 'legacy-user-' || id || '@placeholder.invalid' WHERE email IS NULL")
    # batch_alter_table: identical direct ALTER statements on Postgres
    # (recreate="auto" only rebuilds the table when the backend actually
    # requires it) — needed here only so this migration can ALSO be run
    # against sqlite, which has no ALTER COLUMN syntax at all. See
    # tests/test_migration_email_backfill.py.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", nullable=False)
        batch_op.alter_column("email_verified", server_default=None)


def downgrade():
    op.drop_column("users", "email_verified")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", nullable=True)