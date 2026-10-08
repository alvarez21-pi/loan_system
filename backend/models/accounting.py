from datetime import datetime

from extensions import db


MONEY = (15, 2)

DEFAULT_ASSET_TYPES = (
    "Land", "Building", "Vehicle", "Motorcycle", "Furniture & Fittings",
    "Computers & Electronics", "Office Equipment", "Machinery", "Other",
)


class AssetType(db.Model):
    __tablename__ = "asset_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    assets = db.relationship("Asset", back_populates="asset_type", lazy=True)


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    # Legacy free-text type, kept for any pre-AssetType rows; the form now uses
    # asset_type_id and this mirrors its name on write.
    type = db.Column(db.String(80), nullable=False)
    # Phase 2 item 12 (F-08): filtered/joined on in the assets listing.
    asset_type_id = db.Column(db.Integer, db.ForeignKey("asset_types.id"), nullable=True, index=True)
    value = db.Column(db.Numeric(*MONEY), nullable=False)
    date_acquired = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    asset_type = db.relationship("AssetType", back_populates="assets", lazy=True)


class Expense(db.Model):
    """Recorded directly by anyone with expenses:manage — no approval workflow
    (Part 1.1). status/approved_by are kept only as a historical audit trail
    column set; every new row is 'recorded' the moment it is created."""

    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(*MONEY), nullable=False)
    # Filtered by date-range reports constantly (routes/reports.py).
    date = db.Column(db.Date, nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_by_name_snapshot = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="recorded")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('recorded', 'pending', 'approved', 'rejected')",
            name="ck_expenses_status",
        ),
    )

    added_by_user = db.relationship("User", foreign_keys=[added_by], lazy=True)

    @property
    def created_by(self):
        return self.added_by


class CapitalEntry(db.Model):
    """Versioned history of the business's opening/adjusted cash capital, plus
    injections and withdrawals. entry_type distinguishes the three; opening is
    unique (one active row, correctable only by CEO with a reason)."""

    __tablename__ = "capital_entries"

    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(20), nullable=False, default="opening")
    # For 'opening': previous_value/new_value track corrections over time.
    # For 'injection'/'withdrawal': amount is the movement; previous/new stay 0.
    previous_value = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    new_value = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    amount = db.Column(db.Numeric(*MONEY), nullable=False, default=0)
    # Filtered by date-range reports constantly (routes/reports.py).
    date = db.Column(db.Date, nullable=True, index=True)
    note = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_name_snapshot = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "entry_type IN ('opening', 'injection', 'withdrawal')",
            name="ck_capital_entries_type",
        ),
    )

    changed_by_user = db.relationship("User", foreign_keys=[changed_by], lazy=True)
