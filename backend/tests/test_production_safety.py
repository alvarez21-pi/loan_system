"""PHASE 2 items 1-2: the app must refuse to start in production with debug
mode on, or with a missing/placeholder/too-short secret. These are startup-
time checks, not request-time behavior, so each test manipulates the
environment directly and calls create_app() itself rather than using the
shared `app` fixture (which always configures a safe test environment).
"""
import importlib
import os

import pytest

REQUIRED_ENV = {
    "JWT_SECRET_KEY": "a" * 48,
    "DATABASE_URL": "postgresql://loanuser:SomeRealPassw0rd123@db:5432/loan_system",
    "EMAIL_SERVICE_SECRET": "b" * 32,
}


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """A from-scratch environment with every startup-relevant var cleared,
    so each test controls exactly what's set."""
    for key in (
        "ENVIRONMENT", "FLASK_DEBUG", "JWT_SECRET_KEY", "DATABASE_URL",
        "EMAIL_SERVICE_SECRET", "FLASK_TESTING", "UPLOAD_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "test.sqlite3"))

    def _create_app():
        import app as app_module
        importlib.reload(app_module)
        return app_module.create_app()

    return _create_app


def test_debug_mode_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="(?i)debug"):
        clean_env()


def test_debug_mode_allowed_in_development(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    flask_app = clean_env()
    assert flask_app.debug is True


def test_missing_jwt_secret_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", REQUIRED_ENV["EMAIL_SERVICE_SECRET"])
    with pytest.raises(RuntimeError, match="(?i)jwt_secret_key"):
        clean_env()


def test_placeholder_jwt_secret_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-this-secret-in-production")
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", REQUIRED_ENV["EMAIL_SERVICE_SECRET"])
    with pytest.raises(RuntimeError, match="(?i)jwt_secret_key"):
        clean_env()


def test_short_jwt_secret_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "short-key-15b")  # well under 32 bytes
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", REQUIRED_ENV["EMAIL_SERVICE_SECRET"])
    with pytest.raises(RuntimeError, match="(?i)32 bytes"):
        clean_env()


def test_placeholder_database_password_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", REQUIRED_ENV["JWT_SECRET_KEY"])
    monkeypatch.setenv("DATABASE_URL", "postgresql://loanuser:changeme@db:5432/loan_system")
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", REQUIRED_ENV["EMAIL_SERVICE_SECRET"])
    with pytest.raises(RuntimeError, match="(?i)database"):
        clean_env()


def test_placeholder_email_secret_refused_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", REQUIRED_ENV["JWT_SECRET_KEY"])
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", "change-this-email-secret")
    with pytest.raises(RuntimeError, match="(?i)email_service_secret"):
        clean_env()


def test_strong_secrets_start_cleanly_in_production(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    flask_app = clean_env()
    assert flask_app.debug is False
