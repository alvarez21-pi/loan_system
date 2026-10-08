import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import text

from extensions import db, jwt, migrate
from routes.auth import auth_bp
from routes.backup import backup_bp
from routes.employees import employees_bp
from routes.payroll import payroll_bp
from routes.resources import resources_bp
from routes.operations import operations_bp
from routes.reports import reports_bp
from routes.users import users_bp
from services.scheduler import start_scheduler
from services.startup_safety import (
    environment_name,
    is_production,
    validate_database_password,
    validate_debug,
    validate_secret,
)


def create_app():
    app = Flask(__name__)

    environment = environment_name()
    app.config["ENVIRONMENT"] = environment

    debug_requested = os.getenv("FLASK_DEBUG", "false").strip().lower() == "true"
    validate_debug(debug_requested, environment)
    # Only ever True when ENVIRONMENT=development explicitly asked for it —
    # never a side effect of running `python app.py` with no config at all.
    app.debug = debug_requested and environment == "development"

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://loanuser:changeme@localhost:5432/loan_system",
    )
    validate_database_password(database_url, environment)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    jwt_secret = os.getenv("JWT_SECRET_KEY", "change-this-secret-in-production")
    validate_secret("JWT_SECRET_KEY", jwt_secret, environment)
    app.config["JWT_SECRET_KEY"] = jwt_secret

    email_secret = os.getenv("EMAIL_SERVICE_SECRET", "change-this-email-secret")
    validate_secret("EMAIL_SERVICE_SECRET", email_secret, environment)

    app.config["FRONTEND_URL"] = os.getenv("FRONTEND_URL", "http://localhost:3000")
    # Phase 7 item 1: unset (the default) means no banner anywhere. Never a
    # secret, so it's fine to expose as-is on the public endpoint below.
    app.config["ENVIRONMENT_LABEL"] = os.getenv("ENVIRONMENT_LABEL", "").strip()
    # Borrower photos / ID documents are stored here and served only through
    # authenticated endpoints, never as static files.
    app.config["UPLOAD_DIR"] = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
    app.config["TESTING"] = os.getenv("FLASK_TESTING", "false").lower() == "true"
    # Set-password link lifetimes (Part 8.3): configurable, sane defaults.
    app.config["VERIFICATION_TOKEN_TTL_HOURS"] = os.getenv("VERIFICATION_TOKEN_TTL_HOURS", "24")
    app.config["PASSWORD_RESET_TTL_MINUTES"] = os.getenv("PASSWORD_RESET_TTL_MINUTES", "60")

    # CORS is only needed when the frontend calls the API cross-origin (local
    # dev without the Nginx proxy). In Docker the frontend proxies /api to the
    # backend itself, so the browser only ever talks to its own origin.
    CORS(app)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    import models  # noqa: F401

    app.register_blueprint(auth_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(operations_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    if not app.testing and (not app.debug or os.getenv("WERKZEUG_RUN_MAIN") == "true"):
        start_scheduler(app)

    @app.after_request
    def no_store_api_responses(response):
        # API data is per-user; never let a browser or proxy replay it for someone else.
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.after_request
    def security_headers(response):
        """Phase 2 item 8: the API itself only ever serves JSON/files, never
        HTML/scripts, so its CSP can be maximally strict — this is
        defense-in-depth for the rare error page a proxy might render, not
        something the app depends on. frame-ancestors/X-Frame-Options stop
        the API being framed for clickjacking; the rest are the standard
        hardening set. HSTS is added only when the request actually arrived
        over HTTPS (directly or via a TLS-terminating proxy's
        X-Forwarded-Proto) — never advertised over plain HTTP, where it
        would be meaningless and could lock out a misconfigured deployment.
        """
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        is_https = request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        if is_https:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.route("/api/health")
    def health():
        # Phase 6: a process that's up but can't reach its database is not
        # healthy — Coolify (or any orchestrator) should restart it, not
        # keep routing traffic to it.
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "database": "ok"})
        except Exception as exc:
            app.logger.error("health check: database unreachable: %s", exc)
            return jsonify({"status": "error", "database": "unreachable"}), 503

    @app.route("/api/environment-label")
    def environment_label():
        """Phase 7 item 1: public (no auth — the login page needs it too),
        read by the frontend on every page to show (or not show) the banner.
        Never a secret, just a plain label like "Test environment"."""
        return jsonify({"environment_label": app.config["ENVIRONMENT_LABEL"] or None})

    return app


app = create_app()

if __name__ == "__main__":
    # Local dev convenience ONLY — the actual container never runs this
    # (Dockerfile's CMD serves `app:app` via gunicorn instead, see Phase 2
    # item 1). `app.debug` was already resolved safely in create_app(): it
    # can only be True here if ENVIRONMENT=development was set explicitly.
    app.run(debug=app.debug, host="0.0.0.0", port=5000)
