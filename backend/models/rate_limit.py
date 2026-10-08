from datetime import datetime

from extensions import db


class RateLimitAttempt(db.Model):
    """Phase 2 item 7: a DB-backed counter per (scope, identifier) — e.g.
    scope="login", identifier="email:a@b.com" or "ip:1.2.3.4" — so the limit
    holds across every gunicorn worker process, not just the one that
    happened to handle a given request."""

    __tablename__ = "rate_limit_attempts"

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(40), nullable=False)
    identifier = db.Column(db.String(255), nullable=False)
    window_start = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("scope", "identifier", name="uq_rate_limit_scope_identifier"),
    )
