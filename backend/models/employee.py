from extensions import db


MONEY = (15, 2)


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    salary = db.Column(db.Numeric(*MONEY), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    payroll_runs = db.relationship("PayrollRun", back_populates="employee", lazy=True)
    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="employee",
        lazy=True,
    )


class PayrollRun(db.Model):
    __tablename__ = "payroll_runs"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    salary_amount = db.Column(db.Numeric(*MONEY), nullable=False)
    deductions = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    net_pay = db.Column(db.Numeric(*MONEY), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'paid')",
            name="ck_payroll_runs_status",
        ),
    )

    employee = db.relationship("Employee", back_populates="payroll_runs")
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)


class LeaveRequest(db.Model):
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    leave_type = db.Column(db.String(80), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    reason = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_leave_requests_status",
        ),
    )

    employee = db.relationship("Employee", back_populates="leave_requests")
