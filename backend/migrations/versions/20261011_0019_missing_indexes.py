"""Phase 2 item 12 (F-08): indexes on the foreign keys, status/date columns
report queries and listings filter on constantly. Postgres never indexes a
foreign key column automatically, so these have been full-table-scanned
since the tables they're on were created.

Revision ID: 20261011_0019
Revises: 20261011_0018
"""
from alembic import op

revision = "20261011_0019"
down_revision = "20261011_0018"
branch_labels = None
depends_on = None


SINGLE_COLUMN_INDEXES = (
    ("ix_loans_borrower_id", "loans", "borrower_id"),
    ("ix_loans_loan_product_id", "loans", "loan_product_id"),
    ("ix_loans_start_date", "loans", "start_date"),
    ("ix_loans_status", "loans", "status"),
    ("ix_repayments_loan_id", "repayments", "loan_id"),
    ("ix_repayments_schedule_id", "repayments", "schedule_id"),
    ("ix_repayments_payment_date", "repayments", "payment_date"),
    ("ix_penalties_date_applied", "penalties", "date_applied"),
    ("ix_assets_asset_type_id", "assets", "asset_type_id"),
    ("ix_expenses_date", "expenses", "date"),
    ("ix_capital_entries_date", "capital_entries", "date"),
    ("ix_payroll_runs_employee_id", "payroll_runs", "employee_id"),
    ("ix_leave_requests_employee_id", "leave_requests", "employee_id"),
    ("ix_leave_requests_start_date", "leave_requests", "start_date"),
    ("ix_audit_logs_user_id", "audit_logs", "user_id"),
    ("ix_audit_logs_timestamp", "audit_logs", "timestamp"),
)

COMPOSITE_INDEXES = (
    ("ix_payment_schedules_loan_id_due_date", "payment_schedules", ["loan_id", "due_date"]),
    ("ix_penalties_loan_id_status", "penalties", ["loan_id", "status"]),
)


def upgrade():
    for name, table, column in SINGLE_COLUMN_INDEXES:
        op.create_index(name, table, [column])
    for name, table, columns in COMPOSITE_INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    for name, table, columns in COMPOSITE_INDEXES:
        op.drop_index(name, table_name=table)
    for name, table, column in SINGLE_COLUMN_INDEXES:
        op.drop_index(name, table_name=table)
