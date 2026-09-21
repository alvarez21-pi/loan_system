import os

from flask import Flask, jsonify
from flask_cors import CORS

from extensions import db, jwt, migrate
from routes.auth import auth_bp
from routes.resources import resources_bp
from routes.operations import operations_bp
from routes.reports import reports_bp
from routes.users import users_bp
from services.scheduler import start_scheduler


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql://loanuser:changeme@localhost:5432/loan_system",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = os.getenv(
        "JWT_SECRET_KEY",
        "change-this-secret-in-production",
    )
    app.config["FRONTEND_URL"] = os.getenv("FRONTEND_URL", "http://localhost:3000")

    CORS(app)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    import models  # noqa: F401

    app.register_blueprint(auth_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(operations_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    if not app.debug or os.getenv("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler(app)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
