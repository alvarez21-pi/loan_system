"""Phase 6 — encrypted backup download, the dashboard staleness check, and
the nightly server-side backup job. The test database is sqlite (see
conftest.py), which services/backup.py handles as a real, first-class
backend (not mocked) — dump_database_bytes() just reads the sqlite file's
own bytes, so these tests exercise the SAME code path a Postgres
deployment does, except for the pg_dump/psql subprocess calls themselves
(verified separately, by hand, against a real throwaway Postgres 15
container — see docs/phase-reports.md's Phase 6 section).
"""
import os
from datetime import datetime, timedelta

import pytest

from extensions import db
from models import BackupLog
from services import backup as backup_service


@pytest.fixture()
def staff(make_user, auth_headers):
    people = {"ceo": make_user("ceo"), "maker": make_user("maker"), "head_manager": make_user("head_manager")}
    users = {role: pair[0] for role, pair in people.items()}
    headers = {role: auth_headers(pair[0].email, pair[1]) for role, pair in people.items()}
    return users, headers


# ------------------------------------------------------------------ status

def test_backup_status_forbidden_for_a_role_without_backup_manage(client, staff):
    _, headers = staff
    response = client.get("/api/backup/status", headers=headers["maker"])
    assert response.status_code == 403


def test_backup_status_is_stale_with_no_prior_download(client, staff):
    _, headers = staff
    response = client.get("/api/backup/status", headers=headers["ceo"])
    assert response.status_code == 200
    body = response.get_json()
    assert body["last_manual_download"] is None
    assert body["stale"] is True
    assert body["stale_after_days"] == 7


def test_backup_status_not_stale_right_after_a_download(client, staff, app):
    _, headers = staff
    response = client.post("/api/backup/download", json={"password": "CorrectHorseBattery1"}, headers=headers["ceo"])
    assert response.status_code == 200

    status = client.get("/api/backup/status", headers=headers["ceo"])
    body = status.get_json()
    assert body["last_manual_download"] is not None
    assert body["stale"] is False


def test_backup_status_stale_again_after_seven_days(client, staff, app):
    _, headers = staff
    with app.app_context():
        db.session.add(BackupLog(kind="manual_download", created_at=datetime.utcnow() - timedelta(days=8)))
        db.session.commit()

    status = client.get("/api/backup/status", headers=headers["ceo"])
    assert status.get_json()["stale"] is True


# ---------------------------------------------------------------- download

def test_backup_download_forbidden_for_a_role_without_backup_manage(client, staff):
    _, headers = staff
    response = client.post("/api/backup/download", json={"password": "CorrectHorseBattery1"}, headers=headers["maker"])
    assert response.status_code == 403


def test_backup_download_rejects_a_short_password(client, staff):
    _, headers = staff
    response = client.post("/api/backup/download", json={"password": "short"}, headers=headers["ceo"])
    assert response.status_code == 400


def test_backup_download_returns_an_encrypted_file_and_logs_it(client, staff, app):
    users, headers = staff
    response = client.post("/api/backup/download", json={"password": "CorrectHorseBattery1"}, headers=headers["head_manager"])
    assert response.status_code == 200
    assert response.mimetype == "application/octet-stream"
    encrypted = response.data
    assert len(encrypted) > 0

    with app.app_context():
        log = BackupLog.query.filter_by(kind="manual_download").order_by(BackupLog.id.desc()).first()
        assert log is not None
        assert log.success is True
        assert log.size_bytes > 0
        assert log.user_id == users["head_manager"].id


def test_backup_download_round_trips_through_decrypt_and_contains_the_database(client, staff, app):
    _, headers = staff
    response = client.post("/api/backup/download", json={"password": "CorrectHorseBattery1"}, headers=headers["ceo"])
    encrypted = response.data

    # A wrong password must fail loudly (GCM tag mismatch), not silently
    # return garbage.
    with pytest.raises(ValueError):
        backup_service.decrypt_backup(encrypted, "TotallyWrongPassword")

    plain_zip = backup_service.decrypt_backup(encrypted, "CorrectHorseBattery1")
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(plain_zip)) as zf:
        names = zf.namelist()
    assert "database.sqlite3" in names


def test_backup_download_includes_uploaded_files(client, staff, app):
    _, headers = staff
    upload_dir = app.config["UPLOAD_DIR"]
    with open(os.path.join(upload_dir, "borrower-photo.jpg"), "wb") as f:
        f.write(b"fake-jpeg-bytes")

    response = client.post("/api/backup/download", json={"password": "CorrectHorseBattery1"}, headers=headers["ceo"])
    plain_zip = backup_service.decrypt_backup(response.data, "CorrectHorseBattery1")
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(plain_zip)) as zf:
        names = zf.namelist()
    assert os.path.join("uploads", "borrower-photo.jpg").replace("\\", "/") in [n.replace("\\", "/") for n in names]


# ------------------------------------------------------------- nightly job

def test_write_nightly_backup_creates_a_file_and_prunes_old_ones(app, tmp_path):
    backup_dir = str(tmp_path / "nightly")
    filename, size_bytes = backup_service.write_nightly_backup(backup_dir, app.config["UPLOAD_DIR"], keep_days=14)
    assert size_bytes > 0
    assert os.path.isfile(os.path.join(backup_dir, filename))

    # An old backup file (mtime far in the past) must be pruned on the next run.
    stale_path = os.path.join(backup_dir, "backup-20200101-000000.zip")
    with open(stale_path, "wb") as f:
        f.write(b"old")
    old_time = (datetime.utcnow() - timedelta(days=30)).timestamp()
    os.utime(stale_path, (old_time, old_time))

    backup_service.write_nightly_backup(backup_dir, app.config["UPLOAD_DIR"], keep_days=14)
    assert not os.path.exists(stale_path)


def test_run_nightly_backup_logs_a_backup_log_row(app, tmp_path, monkeypatch):
    from services import scheduler as scheduler_service

    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "nightly2"))
    scheduler_service.run_nightly_backup(app)

    with app.app_context():
        log = BackupLog.query.filter_by(kind="nightly").order_by(BackupLog.id.desc()).first()
        assert log is not None
        assert log.success is True
        assert log.size_bytes > 0
