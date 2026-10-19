from datetime import datetime

from extensions import db


ID_TYPES = ("nida", "driving_licence", "voter_id", "passport", "other")


class Borrower(db.Model):
    __tablename__ = "borrowers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    id_type = db.Column(db.String(20), nullable=False, default="nida")
    # Optional at creation (Part: ID pending) — a borrower can be registered
    # before their ID is submitted. Postgres treats NULL as distinct in a
    # multi-column unique constraint, so any number of "ID pending"
    # borrowers can coexist without tripping uq_borrowers_id_type_number.
    id_number = db.Column(db.String(80), nullable=True, index=True)
    id_verified = db.Column(db.Boolean, nullable=False, default=False)
    id_verified_at = db.Column(db.DateTime, nullable=True)
    id_verification_source = db.Column(db.String(80), nullable=True)
    address = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)  # legacy; uploads use photo_path
    # Uploaded files live under UPLOAD_DIR; only the generated file name is stored.
    photo_path = db.Column(db.String(255), nullable=True)
    id_document_path = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Soft-delete (a borrower with any loan history can never be hard-deleted
    # — it would orphan the loans referencing them). Mirrors User.deactivate()/
    # reactivate() exactly.
    deactivated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("id_type", "id_number", name="uq_borrowers_id_type_number"),
        db.CheckConstraint(
            "id_type IN ('nida', 'driving_licence', 'voter_id', 'passport', 'other')",
            name="ck_borrowers_id_type",
        ),
    )

    loans = db.relationship("Loan", back_populates="borrower", lazy=True)
    notes = db.relationship(
        "BorrowerNote", back_populates="borrower", lazy=True, order_by="BorrowerNote.created_at.desc()",
    )

    def deactivate(self):
        self.is_active = False
        self.deactivated_at = datetime.utcnow()

    def reactivate(self):
        self.is_active = True
        self.deactivated_at = None

    @property
    def has_loan_history(self):
        return len(self.loans) > 0


class BorrowerEditRequest(db.Model):
    """A proposed change to a borrower — edit, deactivate (soft delete), or
    hard_delete — routed through the SAME maker-checker machinery as loans
    and penalties (services/approval.py's approval_denial(), routes/
    operations.py's decide_record()). The live Borrower row is never
    touched until this is approved; only one row per borrower may be
    'pending' at a time (enforced by the partial unique index below AND by
    the route, which checks first — the index is the race-proof backstop).

    `changes` is a JSON {field: {"old": ..., "new": ...}} diff for an
    'edit' (empty for deactivate/hard_delete). `reason` is free text (e.g.
    why a deletion is being requested). borrower_name_snapshot keeps this
    row readable in history even if the borrower is later hard-deleted —
    borrower_id itself is nullable, SET NULL on the borrower's removal.
    """

    __tablename__ = "borrower_edit_requests"
    approval_permission = "borrowers:approve"

    id = db.Column(db.Integer, primary_key=True)
    borrower_id = db.Column(db.Integer, db.ForeignKey("borrowers.id", ondelete="SET NULL"), nullable=True, index=True)
    borrower_name_snapshot = db.Column(db.String(160), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    changes = db.Column(db.JSON, nullable=False, default=dict)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_name_snapshot = db.Column(db.String(120), nullable=True)
    approver_name_snapshot = db.Column(db.String(120), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("action IN ('edit', 'deactivate', 'hard_delete')", name="ck_borrower_edit_requests_action"),
        db.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_borrower_edit_requests_status"),
        db.Index(
            "uq_borrower_edit_requests_one_pending",
            "borrower_id",
            unique=True,
            postgresql_where=db.text("status = 'pending'"),
        ),
    )

    borrower = db.relationship("Borrower")
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    approver = db.relationship("User", foreign_keys=[approved_by], lazy=True)


class BorrowerNote(db.Model):
    """A timestamped, authored log entry on a borrower (Part: Notes) —
    append-only, never edited or overwritten, so the history of why a flag
    was raised (e.g. "ID still pending, following up") is always kept.
    Posted directly, no approval needed: informational, not a change to
    the borrower's own financial/identity data."""

    __tablename__ = "borrower_notes"

    id = db.Column(db.Integer, primary_key=True)
    borrower_id = db.Column(db.Integer, db.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name_snapshot = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    borrower = db.relationship("Borrower", back_populates="notes")
    author = db.relationship("User", foreign_keys=[author_id], lazy=True)
