from datetime import datetime

from extensions import db


MONEY = (15, 2)
RATE = (5, 2)


class LoanProduct(db.Model):
    __tablename__ = "loan_products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    # MONTHLY interest rate in percent (10 = 10% per month), used directly as the
    # per-period EMI rate. Never an annual rate; nothing divides it by 12.
    default_interest_rate = db.Column(db.Numeric(*RATE), nullable=False, comment="Monthly interest rate in percent (10 = 10% per month)")
    # NOT used to lock or default a loan's term any more (16-part-v2 Part 2 -
    # this was a bug: term used to be force-set to this value whenever a
    # product was selected, with no way to pick anything else). A selected
    # product locks ONLY its interest_rate. Kept only for backward
    # compatibility with existing rows; min/max_term_months below are what
    # actually bounds a loan's term now (as validation only, never a fixed
    # value).
    default_term_months = db.Column(db.Integer, nullable=False, server_default="12")
    # Limits are optional: a NULL limit means "no restriction" at loan creation.
    min_term_months = db.Column(db.Integer, nullable=True)
    max_term_months = db.Column(db.Integer, nullable=True)
    min_amount = db.Column(db.Numeric(*MONEY), nullable=True)
    max_amount = db.Column(db.Numeric(*MONEY), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    loans = db.relationship("Loan", back_populates="loan_product", lazy=True)


class Loan(db.Model):
    __tablename__ = "loans"
    approval_permission = "loans:approve"

    id = db.Column(db.Integer, primary_key=True)
    # Phase 2 item 12 (F-08): Postgres does not index foreign keys
    # automatically, and this column is filtered/joined on constantly
    # (a borrower's own loan list, repayment allocation, reports).
    borrower_id = db.Column(db.Integer, db.ForeignKey("borrowers.id"), nullable=False, index=True)
    # Null for a negotiated/custom loan (Part 4.2) — the Maker enters
    # principal/rate/term directly instead of picking a product. When a
    # product IS selected, its rate and term are locked (Part 4.3): the loan
    # always carries its OWN interest_rate/term_months either way, so
    # loan_calculator.py (and repayment reconciliation) never has to care
    # whether a product was involved.
    loan_product_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_products.id"),
        nullable=True,
        index=True,
    )
    principal_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    # MONTHLY interest rate in percent (10 = 10% per month), used directly as the
    # per-period EMI rate. Never an annual rate; nothing divides it by 12.
    interest_rate = db.Column(db.Numeric(*RATE), nullable=False, comment="Monthly interest rate in percent (10 = 10% per month)")
    term_months = db.Column(db.Integer, nullable=False)
    # The instalment-rounding step this loan was created with (Part 1.2) —
    # copied from the company setting AT CREATION TIME and used for every
    # later recalculation on this loan. Changing the company setting later
    # never alters an existing loan's own step.
    rounding_step = db.Column(db.Integer, nullable=False, server_default="1000")
    # Filtered by date-range reports constantly (routes/reports.py).
    start_date = db.Column(db.Date, nullable=False, index=True)
    # Filtered on in almost every loan listing/dashboard query.
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    outstanding_balance = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_name_snapshot = db.Column(db.String(120), nullable=True)
    approver_name_snapshot = db.Column(db.String(120), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Set the moment an approve/reject decision is actually made — lets a
    # second approver acting on stale data be told exactly who beat them to
    # it and when (Part 8), instead of a generic "already decided" error.
    decided_at = db.Column(db.DateTime, nullable=True)
    # Phase 2 item 4: optimistic-lock counter. SQLAlchemy includes
    # "WHERE lock_version = <current>" on every UPDATE for this row and
    # raises StaleDataError if another transaction already changed it —
    # the cross-database guarantee behind the SELECT ... FOR UPDATE calls in
    # routes/operations.py that a second concurrent decide/repayment can
    # never silently apply on top of stale data.
    lock_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ("
            "'draft', 'pending_approval', 'approved', 'active', "
            "'closed', 'rejected'"
            ")",
            name="ck_loans_status",
        ),
    )
    __mapper_args__ = {"version_id_col": lock_version}

    borrower = db.relationship("Borrower", back_populates="loans")
    loan_product = db.relationship("LoanProduct", back_populates="loans")
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)
    schedules = db.relationship("PaymentSchedule", back_populates="loan", lazy=True)
    repayments = db.relationship("Repayment", back_populates="loan", lazy=True)
    penalties = db.relationship("Penalty", back_populates="loan", lazy=True)


class PaymentSchedule(db.Model):
    __tablename__ = "payment_schedules"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    expected_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    principal_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    interest_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="upcoming")
    # Phase 3 item 2: set once, when the row is first created, and never
    # overwritten afterward — so a report can always tell how far behind
    # the ORIGINAL plan a loan is, regardless of how many times its
    # schedule has since been pushed back for missed periods.
    original_due_date = db.Column(db.Date, nullable=True)
    # How many times this row's due_date has been pushed back by a missed
    # period (Phase 3 item 2). 0 for a row that has never been delayed.
    delayed_months = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # Kept for existing rows/reports; no longer set to True by new
    # repayments (a row whose instalment was underpaid is now 'partial',
    # never 'paid' — see apply_repayment()).
    paid_less_than_scheduled = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    # The instalment amount originally scheduled for THIS row, set once at
    # creation and never overwritten again (same immutable-snapshot pattern
    # as original_due_date) — so a partially-paid row can always show what
    # was due even after expected_amount itself has been reduced to the
    # residual still owed.
    original_expected_amount = db.Column(db.Numeric(*MONEY), nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('upcoming', 'paid', 'partial', 'late', 'missed')",
            name="ck_payment_schedules_status",
        ),
        # Phase 2 item 12 (F-08): every repayment allocation and report
        # walks a loan's open schedule rows in due_date order.
        db.Index("ix_payment_schedules_loan_id_due_date", "loan_id", "due_date"),
    )

    loan = db.relationship("Loan", back_populates="schedules")
    repayments = db.relationship("Repayment", back_populates="schedule", lazy=True)


class Repayment(db.Model):
    __tablename__ = "repayments"

    id = db.Column(db.Integer, primary_key=True)
    # Phase 2 item 12 (F-08): looked up by loan constantly (reconciliation,
    # loan detail page, capital breakdown).
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False, index=True)
    schedule_id = db.Column(
        db.Integer,
        db.ForeignKey("payment_schedules.id"),
        nullable=True,
        index=True,
    )
    amount_paid = db.Column(db.Numeric(*MONEY), nullable=False)
    # Filtered by date-range reports constantly (routes/reports.py).
    payment_date = db.Column(db.Date, nullable=False, index=True)
    principal_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    interest_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    balance_after = db.Column(db.Numeric(*MONEY), nullable=False)
    # Phase 2 item 5: a client-generated key, one per submission of the
    # repayment/settle form. A retried/double-fired submit resends the SAME
    # key, so the unique constraint below turns the repeat into a no-op
    # instead of a second payment. Nullable only so existing rows (seeded
    # before this column existed) don't need a backfill — every NEW
    # repayment is required to supply one (enforced in routes/operations.py,
    # not at the DB level, since NULL can't be the thing a UNIQUE constraint
    # rejects duplicates of).
    idempotency_key = db.Column(db.String(64), nullable=True, unique=True)

    loan = db.relationship("Loan", back_populates="repayments")
    schedule = db.relationship("PaymentSchedule", back_populates="repayments")


class Penalty(db.Model):
    __tablename__ = "penalties"
    approval_permission = "penalties:approve"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    amount = db.Column(db.Numeric(*MONEY), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    # Filtered by date-range reports constantly (routes/reports.py).
    date_applied = db.Column(db.Date, nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_by_name_snapshot = db.Column(db.String(120), nullable=True)
    approver_name_snapshot = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    reversed_at = db.Column(db.DateTime, nullable=True)
    reversed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reversed_by_name_snapshot = db.Column(db.String(120), nullable=True)
    reversal_reason = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    # See Loan.decided_at — same purpose (Part 8).
    decided_at = db.Column(db.DateTime, nullable=True)
    # See Loan.lock_version — same purpose (Phase 2 item 4).
    lock_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'reversed')",
            name="ck_penalties_status",
        ),
        # Phase 2 item 12 (F-08): a loan's penalty list is filtered by
        # status constantly (approval queues, outstanding-balance checks).
        db.Index("ix_penalties_loan_id_status", "loan_id", "status"),
    )
    __mapper_args__ = {"version_id_col": lock_version}

    loan = db.relationship("Loan", back_populates="penalties")
    added_by_user = db.relationship("User", foreign_keys=[added_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)
    reverser = db.relationship("User", foreign_keys=[reversed_by], lazy=True)

    @property
    def created_by(self):
        return self.added_by
