"""Loan gains loan_type ('reducing_balance', the existing default, or
'interest_only' — new). Borrower edits and loan edits no longer go through
maker-checker: this migration is schema-only (loan_type column), since
removing an approval STEP is a routes/operations.py behavior change, not a
schema one — borrower_edit_requests (still used for deactivate/hard_delete)
is untouched.

Revision ID: 20261023_0031
Revises: 20261022_0030
"""
from alembic import op
import sqlalchemy as sa

revision = "20261023_0031"
down_revision = "20261022_0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "loans",
        sa.Column("loan_type", sa.String(20), nullable=False, server_default="reducing_balance"),
    )
    op.create_check_constraint(
        "ck_loans_loan_type", "loans", "loan_type IN ('reducing_balance', 'interest_only')",
    )


def downgrade():
    op.drop_constraint("ck_loans_loan_type", "loans", type_="check")
    op.drop_column("loans", "loan_type")
