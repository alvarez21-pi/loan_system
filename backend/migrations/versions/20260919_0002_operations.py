"""add borrower email and asset soft-delete flag

Revision ID: 20260919_0002
Revises: 20260916_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260919_0002"
down_revision = "20260916_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("borrowers", sa.Column("email", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_borrowers_email"), "borrowers", ["email"], unique=False)
    op.add_column("assets", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("assets", "is_active", server_default=None)
    op.add_column("leave_requests", sa.Column("created_by", sa.Integer(), nullable=True))
    op.add_column("leave_requests", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_leave_requests_created_by", "leave_requests", "users", ["created_by"], ["id"])
    op.execute("UPDATE leave_requests SET created_by = (SELECT id FROM users ORDER BY id LIMIT 1)")
    op.alter_column("leave_requests", "created_by", nullable=False)


def downgrade():
    op.drop_column("assets", "is_active")
    op.drop_constraint("fk_leave_requests_created_by", "leave_requests", type_="foreignkey")
    op.drop_column("leave_requests", "rejection_reason")
    op.drop_column("leave_requests", "created_by")
    op.drop_index(op.f("ix_borrowers_email"), table_name="borrowers")
    op.drop_column("borrowers", "email")