from datetime import datetime

from extensions import db


MONEY = (15, 2)
RATE = (5, 2)


class LoanProduct(db.Model):
    __tablename__ = "loan_products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    default_interest_rate = db.Column(db.Numeric(*RATE), nullable=False)
    min_term_months = db.Column(db.Integer, nullable=False)
    max_term_months = db.Column(db.Integer, nullable=False)
    min_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    max_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    loans = db.relationship("Loan", back_populates="loan_product", lazy=True)


class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    borrower_id = db.Column(db.Integer, db.ForeignKey("borrowers.id"), nullable=False)
    loan_product_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_products.id"),
        nullable=False,
    )
    principal_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    interest_rate = db.Column(db.Numeric(*RATE), nullable=False)
    term_months = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="draft")
    outstanding_balance = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ("
            "'draft', 'pending_approval', 'approved', 'active', "
            "'closed', 'rejected'"
            ")",
            name="ck_loans_status",
        ),
    )

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

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('upcoming', 'paid', 'partial', 'late', 'missed')",
            name="ck_payment_schedules_status",
        ),
    )

    loan = db.relationship("Loan", back_populates="schedules")
    repayments = db.relationship("Repayment", back_populates="schedule", lazy=True)


class Repayment(db.Model):
    __tablename__ = "repayments"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    schedule_id = db.Column(
        db.Integer,
        db.ForeignKey("payment_schedules.id"),
        nullable=True,
    )
    amount_paid = db.Column(db.Numeric(*MONEY), nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    principal_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    interest_portion = db.Column(db.Numeric(*MONEY), nullable=False)
    balance_after = db.Column(db.Numeric(*MONEY), nullable=False)

    loan = db.relationship("Loan", back_populates="repayments")
    schedule = db.relationship("PaymentSchedule", back_populates="repayments")


class Penalty(db.Model):
    __tablename__ = "penalties"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    amount = db.Column(db.Numeric(*MONEY), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    date_applied = db.Column(db.Date, nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_penalties_status",
        ),
    )

    loan = db.relationship("Loan", back_populates="penalties")
    added_by_user = db.relationship("User", foreign_keys=[added_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)

    @property
    def created_by(self):
        return self.added_by
