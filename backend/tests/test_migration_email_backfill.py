"""Phase 2 item 10 (F-10): migration 20260921_0003 tightens users.email to
NOT NULL with no backfill. email was nullable from the initial schema
(20260916_0001) onward, so a database that already has a user row with a
NULL email — exactly what a demo/seed database, or any real deployment
upgraded from an early revision, can have — must still be able to reach
this migration without failing.

Proven here by actually running Alembic (not db.create_all()) against a
throwaway sqlite file: the users table is built exactly as revision
20260919_0002 (the revision immediately before this one — 0002 never
touches the users table itself) leaves it, alembic_version is stamped at
that revision, a NULL-email row is inserted by hand, then migration 0003
is run via Alembic's command API.

(The full 0001-through-head chain can't be run against sqlite in this
sandbox — an unrelated, pre-existing migration, 20260919_0002, does
`ALTER TABLE assets ALTER COLUMN ... DROP DEFAULT`, which only Postgres's
ALTER COLUMN syntax supports; sqlite has no live Postgres available here
to test against instead. Starting from the exact pre-0003 schema isolates
the fix under test from that unrelated, out-of-scope incompatibility.)
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, text


PRE_MIGRATION_SCHEMA = """
CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(30) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL,
    CONSTRAINT ck_users_role CHECK (role IN ('admin', 'maker', 'checker')),
    UNIQUE (phone)
);
"""


@pytest.fixture()
def migration_env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    uploads = tempfile.mkdtemp(prefix="lms-migration-uploads-")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("UPLOAD_DIR", uploads)

    import importlib
    import app as app_module
    importlib.reload(app_module)
    flask_app = app_module.create_app()
    yield flask_app, db_url
    try:
        os.remove(path)
    except OSError:
        pass


def test_a_legacy_null_email_user_survives_migration_0003(migration_env):
    from flask_migrate import upgrade as migrate_upgrade

    flask_app, db_url = migration_env

    # Build the schema exactly as revision 20260919_0002 leaves it (the
    # revision immediately before 0003 — it never touches `users`), stamped
    # so Alembic knows it's already "at" that revision.
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(PRE_MIGRATION_SCHEMA))
        conn.execute(text(
            "INSERT INTO users (name, email, phone, password_hash, role, is_active) "
            "VALUES ('Legacy User', NULL, '0700000000', 'x', 'maker', 1)"
        ))
    engine.dispose()

    with flask_app.app_context():
        from flask_migrate import stamp
        stamp(revision="20260919_0002")
        # This must not raise — migration 0003's backfill is what's being tested.
        migrate_upgrade(revision="20260921_0003")

    engine = create_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, email, email_verified FROM users WHERE name = 'Legacy User'")).first()
    engine.dispose()

    assert row is not None
    assert row.email == f"legacy-user-{row.id}@placeholder.invalid"
    # Backfilled rows were never a real verified address.
    assert not row.email_verified
