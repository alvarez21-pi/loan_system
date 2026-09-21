from extensions import db


MONEY = (15, 2)


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    type = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Numeric(*MONEY), nullable=False)
    date_acquired = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(*MONEY), nullable=False)
    date = db.Column(db.Date, nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_expenses_status",
        ),
    )

    added_by_user = db.relationship("User", foreign_keys=[added_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)

    @property
    def created_by(self):
        return self.added_by
