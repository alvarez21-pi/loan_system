"""Shared account-creation helpers: one path for making a login, whether it
starts from the Users page or from the Employees page."""
import os
import re
import threading
from email.utils import parseaddr

from flask import current_app
from itsdangerous import URLSafeTimedSerializer

from extensions import db
from models import User
from services.email_client import send_email
from services.permissions import ASSIGNABLE_ROLES, DEPARTMENTS, SCOPED_ROLES, can_create_tier

# Roles that default to also creating an Employee record when created from the
# Users page (an explicit choice on the form, not a silent default — Part 2.1).
LINKABLE_ROLES = ASSIGNABLE_ROLES


class AccountError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_email(value):
    if not isinstance(value, str) or not value.strip():
        return None
    email = value.strip().lower()
    if parseaddr(email)[1] != email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return None
    return email


def reset_serializer():
    return URLSafeTimedSerializer(
        current_app.config["JWT_SECRET_KEY"],
        salt="loan-system-password-reset",
    )


def reset_token(user, purpose="password_reset"):
    # `v` pins this token to the user's CURRENT credentials_version — bumped
    # only when a token is actually consumed, so a used/superseded link stops
    # validating immediately while other freshly-issued (e.g. resent) links
    # for the same user, still carrying the same version, stay good (Part 2).
    return reset_serializer().dumps({"user_id": user.id, "purpose": purpose, "v": user.credentials_version})


def setup_link(user):
    return f'{current_app.config["FRONTEND_URL"]}/?setup={reset_token(user, "account_setup")}'


def reset_link(user):
    return f'{current_app.config["FRONTEND_URL"]}/?token={reset_token(user, "password_reset")}'


def _send_and_log(app, email_type, to, data):
    """The actual send-then-check-the-result logic, with no threading of
    its own — send_email_async wraps this in a background thread for real
    request handling; a test calls it directly, synchronously, so its
    logging is never entangled with whatever other background threads
    happen to be in flight elsewhere in the process (see send_email_async's
    own docstring for why that entanglement is a real problem, not a
    hypothetical one).

    Part 3 finding: `send_email()` never raises on a failed send — a network
    error, timeout, or a non-2xx/malformed response from email-service is
    caught internally and returned as `{"error": ...}`. The `except Exception`
    below only ever catches something send_email() itself can't handle, so a
    genuinely failed send (the actual cause of "the first attempt silently
    didn't arrive") was being thrown away with zero trace of it happening —
    nothing in these logs, nothing anywhere. Now the result is always
    checked, and a failure is logged loudly with the reason, so a real outage
    (e.g. email-service not accepting connections yet right after backend
    startup — see docker-compose.yml's healthcheck-gated depends_on, which
    closes the other half of this race) is visible instead of invisible.
    """
    with app.app_context():
        try:
            result = send_email(email_type, to, data)
        except Exception:
            app.logger.exception("async email send failed: type=%s to=%s", email_type, to)
            return
        if not isinstance(result, dict) or result.get("status") != "sent":
            app.logger.error(
                "async email send did not succeed: type=%s to=%s result=%s", email_type, to, result,
            )


def send_email_async(email_type, to, data):
    """Fire-and-forget email send so the HTTP response never waits on SMTP.

    Runs inside the current app's context since the background thread has no
    request context of its own.

    Returns the Thread (every real caller in this codebase ignores it —
    fire-and-forget) only so a test can confirm it was actually started;
    tests that need to assert on the LOGGING behavior should call
    _send_and_log() directly and synchronously instead of racing a thread
    against ambient background noise from other tests' own unmocked email
    sends (this suite doesn't globally mock send_email — plenty of other
    tests legitimately trigger a real, failing send against the test
    config's deliberately-invalid EMAIL_SERVICE_URL, each on its own
    leftover daemon thread).
    """
    app = current_app._get_current_object()
    thread = threading.Thread(target=_send_and_log, args=(app, email_type, to, data), daemon=True)
    thread.start()
    return thread


def parse_department(value):
    if value in (None, ""):
        return None
    if value not in DEPARTMENTS:
        raise AccountError(f"department must be one of: {', '.join(DEPARTMENTS)}")
    return value


def create_login(creator, *, name, email, phone, role, department=None):
    """Create an unverified User and queue its set-password email.

    Does not commit — the caller owns the transaction so an Employee can be
    created atomically alongside. Raises AccountError for anything the caller
    should turn into a 4xx response. Who may create which tier (in which
    department) is Part 1's hierarchy, enforced here via can_create_tier() —
    the one place this rule lives, so every entry point (Users page, register,
    the Employees page's "create login" action) is held to it identically.
    """
    email = normalize_email(email)
    if email is None:
        raise AccountError("a valid email is required")
    if not all(isinstance(value, str) and value.strip() for value in (name, phone)):
        raise AccountError("name, email, and phone are required")
    if role not in ASSIGNABLE_ROLES:
        raise AccountError(f"role must be one of: {', '.join(sorted(ASSIGNABLE_ROLES))}")
    if role in SCOPED_ROLES and department is None:
        raise AccountError(f"department is required for a {role.replace('_', ' ')} account")
    if not can_create_tier(creator, role, department):
        raise AccountError("you don't have permission to create this type of account", 403)
    if User.query.filter((User.email == email) | (User.phone == phone.strip())).first():
        raise AccountError("email or phone is already registered", 409)

    user = User(
        name=name.strip(), email=email, phone=phone.strip(), role=role,
        department=department if role in SCOPED_ROLES else None, email_verified=False,
    )
    user.set_password(os.urandom(32).hex())
    db.session.add(user)
    db.session.flush()
    return user


def queue_setup_email(user):
    send_email_async("verification", user.email, {"name": user.name, "verify_link": setup_link(user)})
