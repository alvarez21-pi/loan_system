"""approval scopes, payroll batches, optional product limits, borrower uploads, employee email

Revision ID: 20260925_0006
Revises: 20260924_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260925_0006"
down_revision = "20260924_0005"
branch_labels = None
depends_on = None

SCOPES = ("loans", "penalties", "expenses", "payroll", "leave_requests")


def upgrade():
    # --- approval scopes (checker role only); existing checkers keep everything ---
    op.create_table(
        "approval_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope", name="uq_approval_scopes_user_scope"),
        sa.CheckConstraint(
            "scope IN ('loans', 'penalties', 'expenses', 'payroll', 'leave_requests')",
            name="ck_approval_scopes_scope",
        ),
    )
    op.create_index(op.f("ix_approval_scopes_user_id"), "approval_scopes", ["user_id"])
    for scope in SCOPES:
        op.execute(
            f"INSERT INTO approval_scopes (user_id, scope) "
            f"SELECT id, '{scope}' FROM users WHERE role = 'checker'"
        )

    # --- loan products: every limit becomes optional (NULL = no restriction) ---
    for column, type_ in (
        ("min_term_months", sa.Integer()),
        ("max_term_months", sa.Integer()),
        ("min_amount", sa.Numeric(15, 2)),
        ("max_amount", sa.Numeric(15, 2)),
    ):
        op.alter_column("loan_products", column, existing_type=type_, nullable=True)

    # --- borrowers: uploaded photo / ID document (file names under UPLOAD_DIR) ---
    op.add_column("borrowers", sa.Column("photo_path", sa.String(length=255), nullable=True))
    op.add_column("borrowers", sa.Column("id_document_path", sa.String(length=255), nullable=True))

    # --- employees: email (payslip delivery) ---
    op.add_column("employees", sa.Column("email", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE employees SET email = users.email FROM users WHERE users.id = employees.user_id"
    )

    # --- rejection reasons were being dropped for expenses and penalties ---
    op.add_column("expenses", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("penalties", sa.Column("rejection_reason", sa.Text(), nullable=True))

    # --- payroll: whole-batch approval, per-employee rows become the batch's lines ---
    op.create_table(
        "payroll_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("creator_name_snapshot", sa.String(length=120), nullable=True),
        sa.Column("approver_name_snapshot", sa.String(length=120), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_payroll_batches_status"),
    )
    op.create_index(op.f("ix_payroll_batches_month"), "payroll_batches", ["month"])
    op.add_column("payroll_runs", sa.Column("batch_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_payroll_runs_batch_id"), "payroll_runs", ["batch_id"])
    op.create_foreign_key(
        "payroll_runs_batch_id_fkey", "payroll_runs", "payroll_batches", ["batch_id"], ["id"], ondelete="CASCADE"
    )

    # Group each month's existing per-employee rows into one batch.
    bind = op.get_bind()
    groups = bind.execute(
        sa.text(
            "SELECT month, created_by, status, MIN(creator_name_snapshot), "
            "MAX(approved_by), MAX(approver_name_snapshot) "
            "FROM payroll_runs GROUP BY month, created_by, status"
        )
    ).fetchall()
    for month, created_by, status, creator_name, approved_by, approver_name in groups:
        batch_id = bind.execute(
            sa.text(
                "INSERT INTO payroll_batches (month, status, created_by, approved_by, "
                "creator_name_snapshot, approver_name_snapshot, created_at) "
                "VALUES (:month, :status, :created_by, :approved_by, :creator_name, :approver_name, now()) "
                "RETURNING id"
            ),
            {
                "month": month,
                "status": "pending" if status == "pending" else "approved",
                "created_by": created_by,
                "approved_by": approved_by,
                "creator_name": creator_name,
                "approver_name": approver_name,
            },
        ).scalar()
        bind.execute(
            sa.text(
                "UPDATE payroll_runs SET batch_id = :batch_id WHERE month = :month "
                "AND status = :status AND created_by IS NOT DISTINCT FROM :created_by"
            ),
            {"batch_id": batch_id, "month": month, "status": status, "created_by": created_by},
        )


def downgrade():
    op.drop_constraint("payroll_runs_batch_id_fkey", "payroll_runs", type_="foreignkey")
    op.drop_index(op.f("ix_payroll_runs_batch_id"), table_name="payroll_runs")
    op.drop_column("payroll_runs", "batch_id")
    op.drop_index(op.f("ix_payroll_batches_month"), table_name="payroll_batches")
    op.drop_table("payroll_batches")

    op.drop_column("penalties", "rejection_reason")
    op.drop_column("expenses", "rejection_reason")
    op.drop_column("employees", "email")
    op.drop_column("borrowers", "id_document_path")
    op.drop_column("borrowers", "photo_path")

    # Restoring NOT NULL needs values; fill unset limits with permissive defaults first.
    op.execute("UPDATE loan_products SET min_term_months = 1 WHERE min_term_months IS NULL")
    op.execute("UPDATE loan_products SET max_term_months = 1200 WHERE max_term_months IS NULL")
    op.execute("UPDATE loan_products SET min_amount = 0 WHERE min_amount IS NULL")
    op.execute("UPDATE loan_products SET max_amount = 999999999999 WHERE max_amount IS NULL")
    for column, type_ in (
        ("min_term_months", sa.Integer()),
        ("max_term_months", sa.Integer()),
        ("min_amount", sa.Numeric(15, 2)),
        ("max_amount", sa.Numeric(15, 2)),
    ):
        op.alter_column("loan_products", column, existing_type=type_, nullable=False)

    op.drop_index(op.f("ix_approval_scopes_user_id"), table_name="approval_scopes")
    op.drop_table("approval_scopes")
