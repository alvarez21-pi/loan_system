"""The same payslip email was being sent to the same person twice — the
"Send" action had no record of whether it had already succeeded, so a
retried request (or a second click) sent a real duplicate. payroll_runs
gains payslip_sent_at, set the first time a send actually succeeds;
sending again now requires an explicit "resend".

Revision ID: 20261019_0027
Revises: 20261018_0026
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0027"
down_revision = "20261018_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_runs", sa.Column("payslip_sent_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("payroll_runs", "payslip_sent_at")
