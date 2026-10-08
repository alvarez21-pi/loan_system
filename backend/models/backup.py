from datetime import datetime

from extensions import db


class BackupLog(db.Model):
    """Phase 6: one row per backup actually produced — a CEO/head_manager's
    interactive encrypted download, or the unattended nightly server-side
    copy (services/scheduler.py). The dashboard's "last backup downloaded
    more than 7 days ago" warning reads the latest `manual_download` row
    only — the nightly job always runs regardless, so it isn't what that
    warning is checking; what it's checking is whether anyone is actually
    taking a copy off the server."""

    __tablename__ = "backup_logs"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)  # "manual_download" | "nightly"
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_name_snapshot = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.Text, nullable=True)

    user = db.relationship("User", lazy=True)
