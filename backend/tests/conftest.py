import os
import shutil
import tempfile

os.environ.setdefault("FLASK_TESTING", "true")
# Phase 2 items 1-2: production-safety checks (strong-secret length, no
# debug mode) are skipped entirely in "testing" — the test suite must not
# need production-grade secrets to run.
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("EMAIL_SERVICE_URL", "http://email-service.invalid/index.php")
os.environ.setdefault("EMAIL_SERVICE_SECRET", "test-secret")

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    uploads = tempfile.mkdtemp(prefix="lms-uploads-")
    os.environ["UPLOAD_DIR"] = uploads

    from app import create_app
    from extensions import db as _db

    flask_app = create_app()
    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()
    try:
        os.remove(path)
    except OSError:
        pass
    shutil.rmtree(uploads, ignore_errors=True)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    from extensions import db as _db
    from models import User
    from services.permissions import SCOPED_ROLES

    def _make(role, name=None, email=None, phone=None, password="Passw0rd!9", active=True, verified=True, department=None):
        n = name or f"{role.title()} User"
        e = email or f"{role}@example.com"
        p = phone or f"07{abs(hash((role, e))) % 10**8:08d}"
        if department is None and role in SCOPED_ROLES:
            # A deliberately narrow default (not "general", which reaches
            # every module) so a test that doesn't care about department
            # scoping still exercises a realistic, limited account — tests
            # that need cross-department behavior pass department= explicitly.
            department = "loans_credit"
        user = User(name=n, email=e, phone=p, role=role, department=department, is_active=active, email_verified=verified)
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        return user, password

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password):
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.get_json()
        return response.get_json()["access_token"]

    return _login


@pytest.fixture()
def auth_headers(login):
    def _headers(email, password):
        return {"Authorization": f"Bearer {login(email, password)}"}

    return _headers
