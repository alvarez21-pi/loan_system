"""Phase 2 items 1-2: refuse to start with an unsafe production config,
instead of silently running with debug on or a placeholder secret.

`ENVIRONMENT` controls this: it defaults to "production" (safe-by-default
— an operator must explicitly opt into relaxed checks), "development"
additionally allows FLASK_DEBUG=true, and "testing" (set by
tests/conftest.py) skips every check below entirely so the test suite
never needs production-grade secrets.
"""
import os
from urllib.parse import urlparse

PLACEHOLDER_SECRETS = {
    "change-this-secret-in-production",
    "change-this-email-secret",
    "changeme",
    "",
}

MIN_SECRET_BYTES = 32


class StartupConfigError(RuntimeError):
    """Raised to refuse to start the app — never caught, by design."""


def environment_name():
    return os.getenv("ENVIRONMENT", "production").strip().lower()


def is_production(environment):
    return environment not in ("development", "testing")


def validate_debug(debug_requested, environment):
    if debug_requested and is_production(environment):
        raise StartupConfigError(
            "FLASK_DEBUG=true is only allowed when ENVIRONMENT=development. "
            "Refusing to start with debug mode in a non-development environment."
        )


def validate_secret(name, value, environment, min_bytes=MIN_SECRET_BYTES):
    """`name` is the env var name, used verbatim in the error message so a
    test (and an operator reading the startup log) can match on it."""
    if not is_production(environment):
        return
    if not value or value in PLACEHOLDER_SECRETS:
        raise StartupConfigError(
            f"{name} is missing or a known placeholder value. Set a real, "
            f"randomly generated secret via the environment before starting "
            f"in a non-development environment."
        )
    if len(value.encode("utf-8")) < min_bytes:
        raise StartupConfigError(f"{name} must be at least {min_bytes} bytes long.")


def validate_database_password(database_url, environment, min_length=12):
    if not is_production(environment):
        return
    password = urlparse(database_url).password or ""
    if not password or password in PLACEHOLDER_SECRETS:
        raise StartupConfigError(
            "DATABASE_URL's password is missing or a known placeholder value "
            "(e.g. 'changeme'). Set a real database password."
        )
    if len(password) < min_length:
        raise StartupConfigError(f"DATABASE_URL's password must be at least {min_length} characters long.")
