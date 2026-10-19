"""Borrower edit/delete now goes through maker-checker, same as loans and
penalties (new borrower_edit_requests table — approval_permission =
"borrowers:approve", reusing services/approval.py's existing machinery
unchanged). Borrower gains a soft-delete pair (deactivated_at, alongside
the already-existing is_active) and id_number becomes optional ("ID
pending"). New borrower_notes table — an append-only, timestamped,
authored log, posted directly (no approval — informational only).

Loan gains 5 borrower_*_snapshot columns, captured once at loan creation,
so an edited borrower never silently rewrites an already-issued loan's
own document. Existing loans are backfilled from their CURRENT borrower
record below — the best data available for loans issued before this
migration; from this point on, every new loan captures its own snapshot
at creation (routes/operations.py's create_loan).

Revision ID: 20261022_0030
Revises: 20261021_0029
"""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0030"
down_revision = "20261021_0029"
branch_labels = None
depends_on = None


def upgrade():
    # --- borrowers: optional ID, soft-delete timestamp ---------------------
    op.alter_column("borrowers", "id_number", existing_type=sa.String(80), nullable=True)
    op.add_column("borrowers", sa.Column("deactivated_at", sa.DateTime(), nullable=True))

    # --- borrower_edit_requests ---------------------------------------------
    op.create_table(
        "borrower_edit_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("borrower_id", sa.Integer(), sa.ForeignKey("borrowers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("borrower_name_snapshot", sa.String(160), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("creator_name_snapshot", sa.String(120), nullable=True),
        sa.Column("approver_name_snapshot", sa.String(120), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("action IN ('edit', 'deactivate', 'hard_delete')", name="ck_borrower_edit_requests_action"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_borrower_edit_requests_status"),
    )
    op.create_index("ix_borrower_edit_requests_borrower_id", "borrower_edit_requests", ["borrower_id"])
    # Partial unique index: at most one PENDING request per borrower at a
    # time — the race-proof backstop behind the route's own check-first.
    op.create_index(
        "uq_borrower_edit_requests_one_pending",
        "borrower_edit_requests",
        ["borrower_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # --- borrower_notes -------------------------------------------------------
    op.create_table(
        "borrower_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("borrower_id", sa.Integer(), sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_name_snapshot", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_borrower_notes_borrower_id", "borrower_notes", ["borrower_id"])
    op.create_index("ix_borrower_notes_created_at", "borrower_notes", ["created_at"])

    # --- loans: borrower snapshot columns + backfill ------------------------
    op.add_column("loans", sa.Column("borrower_name_snapshot", sa.String(160), nullable=True))
    op.add_column("loans", sa.Column("borrower_phone_snapshot", sa.String(30), nullable=True))
    op.add_column("loans", sa.Column("borrower_id_type_snapshot", sa.String(20), nullable=True))
    op.add_column("loans", sa.Column("borrower_id_number_snapshot", sa.String(80), nullable=True))
    op.add_column("loans", sa.Column("borrower_address_snapshot", sa.Text(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        """
        UPDATE loans
        SET borrower_name_snapshot = borrowers.name,
            borrower_phone_snapshot = borrowers.phone,
            borrower_id_type_snapshot = borrowers.id_type,
            borrower_id_number_snapshot = borrowers.id_number,
            borrower_address_snapshot = borrowers.address
        FROM borrowers
        WHERE loans.borrower_id = borrowers.id
        """
    ))


def downgrade():
    op.drop_column("loans", "borrower_address_snapshot")
    op.drop_column("loans", "borrower_id_number_snapshot")
    op.drop_column("loans", "borrower_id_type_snapshot")
    op.drop_column("loans", "borrower_phone_snapshot")
    op.drop_column("loans", "borrower_name_snapshot")

    op.drop_index("ix_borrower_notes_created_at", table_name="borrower_notes")
    op.drop_index("ix_borrower_notes_borrower_id", table_name="borrower_notes")
    op.drop_table("borrower_notes")

    op.drop_index("uq_borrower_edit_requests_one_pending", table_name="borrower_edit_requests")
    op.drop_index("ix_borrower_edit_requests_borrower_id", table_name="borrower_edit_requests")
    op.drop_table("borrower_edit_requests")

    op.drop_column("borrowers", "deactivated_at")
    op.alter_column("borrowers", "id_number", existing_type=sa.String(80), nullable=False)
