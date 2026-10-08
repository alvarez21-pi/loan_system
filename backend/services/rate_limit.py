"""Phase 2 item 7: DB-backed rate limiting (works identically across every
gunicorn worker process, unlike an in-memory counter local to one) for the
auth endpoints most exposed to brute force / enumeration: login,
password-reset/request (forgot password), resend-verification,
password-reset/validate ("verify") and password-reset/confirm
("set-password").

Limits apply per-identifier — the caller passes one bucket per IP and,
where an email was submitted, one per account — so a lockout is both
per-account and per-IP (whichever is hit first blocks the request).
Responses stay generic: callers return the SAME "too many attempts"
message regardless of which bucket tripped it or whether the submitted
email is even registered.
"""
from datetime import datetime, timedelta

from flask import jsonify, request

from extensions import db
from models import RateLimitAttempt

WINDOW = timedelta(minutes=15)
MAX_ATTEMPTS = 8
LOCKOUT = timedelta(minutes=15)


class RateLimited(Exception):
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("rate limited")


def _get_or_create(scope, identifier, now):
    row = (
        RateLimitAttempt.query.filter_by(scope=scope, identifier=identifier)
        .with_for_update()
        .first()
    )
    if row is None:
        row = RateLimitAttempt(scope=scope, identifier=identifier, window_start=now, attempt_count=0)
        db.session.add(row)
        db.session.flush()
    return row


def check(scope, identifiers):
    """Raise RateLimited if ANY identifier is currently locked out. Call
    this BEFORE doing the real work (e.g. before checking a password), so
    an already-locked account/IP never gets a fresh success/failure signal."""
    now = datetime.utcnow()
    for identifier in identifiers:
        row = _get_or_create(scope, identifier, now)
        if row.locked_until and row.locked_until > now:
            db.session.commit()
            raise RateLimited(int((row.locked_until - now).total_seconds()))
    db.session.commit()


def record_failure(scope, identifiers):
    """Increments each identifier's counter (resetting it first if the
    window has rolled over), locking out any identifier that just reached
    MAX_ATTEMPTS. Call after a failed attempt — or, for an endpoint whose
    response is deliberately generic regardless of outcome (resend-
    verification, forgot-password, verify, set-password), unconditionally
    on every call."""
    now = datetime.utcnow()
    for identifier in identifiers:
        row = _get_or_create(scope, identifier, now)
        if now - row.window_start > WINDOW:
            row.window_start = now
            row.attempt_count = 0
            row.locked_until = None
        row.attempt_count += 1
        if row.attempt_count >= MAX_ATTEMPTS:
            row.locked_until = now + LOCKOUT
    db.session.commit()


def record_success(scope, identifiers):
    """Clears the counter on a genuine success (e.g. correct login) so a
    few earlier typos don't linger toward a lockout later in the window."""
    now = datetime.utcnow()
    for identifier in identifiers:
        row = RateLimitAttempt.query.filter_by(scope=scope, identifier=identifier).with_for_update().first()
        if row is not None:
            row.attempt_count = 0
            row.locked_until = None
            row.window_start = now
    db.session.commit()


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def identifiers_for(email=None):
    ids = [f"ip:{client_ip()}"]
    if email:
        ids.append(f"email:{email}")
    return ids


def rate_limit_response():
    return jsonify({"message": "Too many attempts. Please wait a while before trying again."}), 429
