"""Phase 7 — test environment mode (no demo data).

1. ENVIRONMENT_LABEL drives a public endpoint the frontend reads to show
   (or not show) a banner on every page.
2. scripts/reset_dev_data.py requires --yes, ENVIRONMENT_LABEL set, and
   ENVIRONMENT != "production".
3. scripts/seed_demo_users.py refuses unless ALLOW_DEMO_SEED=true — a
   dedicated opt-in flag, not ENVIRONMENT/ENVIRONMENT_LABEL (both are
   deliberately identical between local and a real deployment, so
   neither can tell the two apart any more — see .env.example).
"""
import importlib

import pytest

REQUIRED_ENV = {
    "JWT_SECRET_KEY": "a" * 48,
    "DATABASE_URL": "postgresql://loanuser:SomeRealPassw0rd123@db:5432/loan_system",
    "EMAIL_SERVICE_SECRET": "b" * 32,
}


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """A from-scratch environment with every startup-relevant var cleared."""
    for key in (
        "ENVIRONMENT", "ENVIRONMENT_LABEL", "FLASK_DEBUG", "JWT_SECRET_KEY", "DATABASE_URL",
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


# --------------------------------------------------------------- item 1: banner

def test_environment_label_endpoint_is_null_when_unset(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "testing")
    app = clean_env()
    client = app.test_client()
    response = client.get("/api/environment-label")
    assert response.status_code == 200
    assert response.get_json() == {"environment_label": None}


def test_environment_label_endpoint_returns_the_label_when_set(clean_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("ENVIRONMENT_LABEL", "Test environment")
    app = clean_env()
    client = app.test_client()
    response = client.get("/api/environment-label")
    assert response.status_code == 200
    assert response.get_json() == {"environment_label": "Test environment"}


def test_environment_label_endpoint_needs_no_auth(clean_env, monkeypatch):
    """The login page itself needs this before anyone is signed in."""
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("ENVIRONMENT_LABEL", "Test environment")
    app = clean_env()
    client = app.test_client()
    response = client.get("/api/environment-label")  # no Authorization header
    assert response.status_code == 200


# --------------------------------------------------------------- item 2: reset script

def test_reset_refuses_without_yes_flag(monkeypatch, app):
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("ENVIRONMENT_LABEL", "Test environment")
    import scripts.reset_dev_data as reset_dev_data
    importlib.reload(reset_dev_data)
    with pytest.raises(SystemExit, match="(?i)--yes"):
        reset_dev_data.main([])


def test_reset_refuses_without_environment_label(monkeypatch, app):
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.delenv("ENVIRONMENT_LABEL", raising=False)
    import scripts.reset_dev_data as reset_dev_data
    importlib.reload(reset_dev_data)
    with pytest.raises(SystemExit, match="(?i)ENVIRONMENT_LABEL"):
        reset_dev_data.main(["--yes"])


def test_reset_refuses_when_environment_is_production(monkeypatch, app):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENVIRONMENT_LABEL", "Test environment")
    import scripts.reset_dev_data as reset_dev_data
    importlib.reload(reset_dev_data)
    with pytest.raises(SystemExit, match="(?i)production"):
        reset_dev_data.main(["--yes"])


def test_reset_runs_when_everything_is_satisfied(monkeypatch, app):
    from extensions import db
    from models import Borrower, User

    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("ENVIRONMENT_LABEL", "Test environment")
    monkeypatch.setenv("CEO_NAME", "Reset CEO")
    monkeypatch.setenv("CEO_EMAIL", "reset-ceo@example.com")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongResetPassw0rd!")

    with app.app_context():
        db.session.add(Borrower(name="Leftover", phone="0700999999", id_type="other", id_number="leftover-1"))
        leftover_user = User(name="Leftover User", email="leftover@example.com", phone="0799999999", role="maker", department="loans_credit", is_active=True, email_verified=True)
        leftover_user.set_password("x")
        db.session.add(leftover_user)
        db.session.commit()
        assert Borrower.query.count() == 1

    import scripts.reset_dev_data as reset_dev_data
    importlib.reload(reset_dev_data)
    reset_dev_data.main(["--yes"])

    with app.app_context():
        assert Borrower.query.count() == 0
        ceo = User.query.filter_by(role="ceo").first()
        assert ceo is not None
        assert ceo.email == "reset-ceo@example.com"
        assert User.query.filter_by(email="leftover@example.com").first() is None


# --------------------------------------------------------------- item 3: demo users

def test_seed_demo_users_refuses_without_allow_demo_seed(monkeypatch, app):
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    import scripts.seed_demo_users as seed_demo_users
    importlib.reload(seed_demo_users)
    with pytest.raises(SystemExit, match="(?i)ALLOW_DEMO_SEED"):
        seed_demo_users.main()


def test_seed_demo_users_refuses_in_production_even_with_other_vars_set(monkeypatch, app):
    """ENVIRONMENT/ENVIRONMENT_LABEL play no part in this gate any more —
    only ALLOW_DEMO_SEED does. Setting ENVIRONMENT=production (as a real
    deployment would) changes nothing here; the absence of
    ALLOW_DEMO_SEED is what refuses it, matching docker-compose.prod.yml
    never defining that variable at all."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    import scripts.seed_demo_users as seed_demo_users
    importlib.reload(seed_demo_users)
    with pytest.raises(SystemExit, match="(?i)ALLOW_DEMO_SEED"):
        seed_demo_users.main()


def test_seed_demo_users_runs_when_allowed(monkeypatch, app):
    from models import User

    monkeypatch.setenv("ALLOW_DEMO_SEED", "true")
    with app.app_context():
        db_ceo = User(
            name="Dev CEO", email="devceo@example.com", phone="255700000000",
            role="ceo", is_active=True, email_verified=True,
        )
        db_ceo.set_password("x")
        from extensions import db
        db.session.add(db_ceo)
        db.session.commit()

    import scripts.seed_demo_users as seed_demo_users
    importlib.reload(seed_demo_users)
    seed_demo_users.main()

    with app.app_context():
        maker = User.query.filter_by(email="maker@example.com").first()
        assert maker is not None
        assert maker.must_change_password is False
        # The spare Maker (for rate-limit testing) and the two fake
        # borrowers are also part of one run.
        assert User.query.filter_by(email="maker2@example.com").first() is not None
        from models import Borrower
        assert Borrower.query.filter_by(id_type="nida", id_number="19900101000011110001").first() is not None
