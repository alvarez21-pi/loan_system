from datetime import datetime

from extensions import db


MONEY = (15, 2)


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    job_title = db.Column(db.String(100), nullable=False)
    salary = db.Column(db.Numeric(*MONEY), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    user = db.relationship("User", backref=db.backref("employee", uselist=False), lazy=True)
    payroll_runs = db.relationship("PayrollRun", back_populates="employee", lazy=True)
    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="employee",
        lazy=True,
    )


class PayrollBatch(db.Model):
    """One monthly payroll run: prepare -> preview/edit/remove lines -> finalize.

    Finalizing (marking the batch paid) is a single action by whoever holds
    payroll:manage — there is no second-person approval (Part 1.5). Payslips
    exist once the batch is paid.
    """

    __tablename__ = "payroll_batches"
    approval_permission = "payroll:manage"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_name_snapshot = db.Column(db.String(120), nullable=True)
    finalizer_name_snapshot = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)
    # See models.loan.Loan.lock_version — same purpose (Phase 2 item 4):
    # guards finalize/cancel against a concurrent finalize/cancel of the
    # same batch.
    lock_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'paid', 'cancelled')",
            name="ck_payroll_batches_status",
        ),
    )
    __mapper_args__ = {"version_id_col": lock_version}

    lines = db.relationship(
        "PayrollRun",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="PayrollRun.id",
        lazy=True,
    )
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    finalizer = db.relationship("User", foreign_keys=[finalized_by], lazy=True)


class PayrollRun(db.Model):
    """A single employee's line item inside a PayrollBatch (also the payslip source).

    `deductions` is the sum of this line's EMPLOYEE-side deduction lines only
    (Part 5.2) — `net_pay` = `salary_amount` - `deductions`. `employer_cost`
    is the sum of EMPLOYER-side lines (e.g. an employer NSSF match) - shown
    separately as a cost to the company, never subtracted from net pay.
    """

    __tablename__ = "payroll_runs"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("payroll_batches.id", ondelete="CASCADE"), nullable=True, index=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    # Phase 2 item 12 (F-08): an employee's payroll history is looked up by this.
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    salary_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    deductions = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    employer_cost = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    net_pay = db.Column(db.Numeric(*MONEY), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_name_snapshot = db.Column(db.String(120), nullable=True)
    # Set the first time this line's payslip email actually sends — the
    # "Send" action then refuses a second send unless the caller explicitly
    # asks to resend, so a flaky network retry or a double click can never
    # silently mail the same payslip twice.
    payslip_sent_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'paid')",
            name="ck_payroll_runs_status",
        ),
    )

    batch = db.relationship("PayrollBatch", back_populates="lines")
    employee = db.relationship("Employee", back_populates="payroll_runs")
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    deduction_lines = db.relationship(
        "PayrollDeductionLine",
        back_populates="payroll_run",
        cascade="all, delete-orphan",
        order_by="PayrollDeductionLine.id",
        lazy=True,
    )


class DeductionType(db.Model):
    """Configurable payroll deduction/contribution (Part 5.2) - NO rate is
    ever hard-coded in code; every actual rate/amount is set here by HR/
    Head Manager/CEO. `calculation`:
    - "fixed": a flat whole-shilling amount every batch.
    - "percentage": `rate` percent of gross salary.
    - "bands": progressive bands (e.g. PAYE) - `bands` is a JSON list of
      {"up_to": <upper bound, or null for the top/unbounded band>, "rate": <percent>},
      ordered lowest to highest, applied marginally (each band's rate only
      on the slice of salary within that band).
    `side`: "employee" (reduces net pay) or "employer" (a cost to the
    company, shown separately, never subtracted from net pay).
    """

    __tablename__ = "deduction_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    calculation = db.Column(db.String(20), nullable=False, default="fixed")
    side = db.Column(db.String(10), nullable=False, default="employee")
    rate = db.Column(db.Numeric(7, 4), nullable=True)  # percent, when calculation == "percentage"
    fixed_amount = db.Column(db.Numeric(*MONEY), nullable=True)  # when calculation == "fixed"
    bands = db.Column(db.JSON, nullable=True)  # when calculation == "bands"
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # "standard" (NSSF and the like): applies to every active employee
    # automatically, as before. "individual" (loan repayment, salary
    # advance, uniform...): applies ONLY to employees with an explicit
    # EmployeeDeduction assignment below, each with its own amount —
    # this type's own rate/fixed_amount/bands are unused for that scope.
    scope = db.Column(db.String(10), nullable=False, default="standard", server_default="standard")

    __table_args__ = (
        db.CheckConstraint("calculation IN ('fixed', 'percentage', 'bands')", name="ck_deduction_types_calculation"),
        db.CheckConstraint("side IN ('employee', 'employer')", name="ck_deduction_types_side"),
        db.CheckConstraint("scope IN ('standard', 'individual')", name="ck_deduction_types_scope"),
    )


class EmployeeDeduction(db.Model):
    """One individual-scope deduction assigned to one employee (Part 5.2
    extension) — e.g. a specific loan repayment of 50,000/month for Jane,
    distinct from Juma's own 30,000 repayment under the same DeductionType.
    Runs from start_month onward, and stops either at end_month (a fixed
    term) or once remaining_balance reaches zero (decremented by the
    amount actually applied each time a batch carrying it is finalized) —
    at most one of those two governs a given assignment."""

    __tablename__ = "employee_deductions"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    deduction_type_id = db.Column(db.Integer, db.ForeignKey("deduction_types.id", ondelete="CASCADE"), nullable=False)
    # Fixed-vs-percentage is chosen PER ASSIGNMENT, independent of the
    # DeductionType's own calculation (which only governs standard-scope
    # types) — two employees can both have "Loan Repayment" with one fixed
    # and the other a percentage of their own gross.
    calculation = db.Column(db.String(10), nullable=False, default="fixed", server_default="fixed")
    amount = db.Column(db.Numeric(*MONEY), nullable=True)  # whole shillings, when calculation == "fixed"
    rate = db.Column(db.Numeric(7, 4), nullable=True)  # percent of gross, when calculation == "percentage"
    start_month = db.Column(db.String(7), nullable=False)  # "YYYY-MM"
    end_month = db.Column(db.String(7), nullable=True)  # "YYYY-MM", inclusive; null = open-ended/balance-governed
    remaining_balance = db.Column(db.Numeric(*MONEY), nullable=True)  # null = not balance-tracked (uses end_month instead)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="true")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint("calculation IN ('fixed', 'percentage')", name="ck_employee_deductions_calculation"),
    )

    employee = db.relationship("Employee", lazy=True)
    deduction_type = db.relationship("DeductionType", lazy=True)


class PayrollDeductionLine(db.Model):
    """One deduction/contribution line on one employee's payroll run (Part
    5.2) — snapshotted (name, side) so a later rename/deactivation of the
    DeductionType never changes a historical payslip's own line."""

    __tablename__ = "payroll_deduction_lines"

    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    deduction_type_id = db.Column(db.Integer, db.ForeignKey("deduction_types.id", ondelete="SET NULL"), nullable=True)
    # Set only for a line generated from an individual EmployeeDeduction
    # assignment — lets finalize_batch() find and decrement the right
    # assignment's remaining_balance. Null for a standard (company-wide) line.
    employee_deduction_id = db.Column(db.Integer, db.ForeignKey("employee_deductions.id", ondelete="SET NULL"), nullable=True)
    name_snapshot = db.Column(db.String(80), nullable=False)
    side = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Numeric(*MONEY), nullable=False)
    # True once this ONE run's amount has been hand-edited — the standing
    # EmployeeDeduction/DeductionType it came from is never touched by that
    # edit, only this line, for this run.
    is_adjusted = db.Column(db.Boolean, nullable=False, default=False, server_default="false")

    __table_args__ = (
        db.CheckConstraint("side IN ('employee', 'employer')", name="ck_payroll_deduction_lines_side"),
    )

    payroll_run = db.relationship("PayrollRun", back_populates="deduction_lines")
    deduction_type = db.relationship("DeductionType", lazy=True)


class LeaveRequest(db.Model):
    """Simple request -> approve/reject by anyone with leave:manage. Not
    maker-checker: a manager/CEO may decide a request regardless of who filed
    it, including one they filed for someone else (Part 1.1)."""

    __tablename__ = "leave_requests"
    approval_permission = "leave:manage"

    id = db.Column(db.Integer, primary_key=True)
    # Phase 2 item 12 (F-08): an employee's own leave history is looked up by this.
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_name_snapshot = db.Column(db.String(120), nullable=True)
    approver_name_snapshot = db.Column(db.String(120), nullable=True)
    leave_type = db.Column(db.String(80), nullable=False)
    # Filtered by date-range reports constantly (routes/reports.py).
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    reason = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    # See models.loan.Loan.decided_at — same purpose (Part 8): tells a second
    # approver acting on stale data exactly who beat them to it, and when.
    decided_at = db.Column(db.DateTime, nullable=True)
    # Editable before approval (Part 9.2): an HR Manager/Head Manager/CEO may
    # adjust the requested dates when deciding, instead of only a binary
    # approve-as-is or reject. Preserves what was originally asked for.
    original_start_date = db.Column(db.Date, nullable=True)
    original_end_date = db.Column(db.Date, nullable=True)
    # See models.loan.Loan.lock_version — same purpose (Phase 2 item 4).
    lock_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_leave_requests_status",
        ),
    )
    __mapper_args__ = {"version_id_col": lock_version}

    employee = db.relationship("Employee", back_populates="leave_requests")
