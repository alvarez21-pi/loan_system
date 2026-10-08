from datetime import datetime

from extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    # Phase 2 item 12 (F-08): the audit log page filters by actor constantly.
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_name_snapshot = db.Column(db.String(120), nullable=True)
    actor_email_snapshot = db.Column(db.String(255), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    table_name = db.Column(db.String(120), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    # The audit log page's default/most-common sort and date-range filter.
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    details = db.Column(db.Text, nullable=True)

    user = db.relationship("User", lazy=True)

    @property
    def actor_display_name(self):
        return self.actor_name_snapshot or (self.user.name if self.user else None)

    @property
    def actor_display_email(self):
        return self.actor_email_snapshot or (self.user.email if self.user else None)
