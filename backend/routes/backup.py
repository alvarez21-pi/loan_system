"""Phase 6: CEO/head_manager-only encrypted backup download, plus the
staleness check the dashboard warns on. See services/backup.py for why the
password is never stored and why the nightly copy (services/scheduler.py)
is unencrypted instead."""
import os
from datetime import datetime, timedelta
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file

from extensions import db
from models import BackupLog
from routes.operations import error, permission_required
from services.backup import encrypt_backup

backup_bp = Blueprint("backup", __name__, url_prefix="/api/backup")

STALE_AFTER_DAYS = 7
MIN_PASSWORD_LENGTH = 12


def last_backup(kind):
    return (
        BackupLog.query.filter_by(kind=kind, success=True)
        .order_by(BackupLog.created_at.desc())
        .first()
    )


def backup_status_payload():
    manual = last_backup("manual_download")
    nightly = last_backup("nightly")
    stale = manual is None or manual.created_at < datetime.utcnow() - timedelta(days=STALE_AFTER_DAYS)
    return {
        "last_manual_download": manual.created_at.isoformat() if manual else None,
        "last_nightly_backup": nightly.created_at.isoformat() if nightly else None,
        "stale": stale,
        "stale_after_days": STALE_AFTER_DAYS,
    }


@backup_bp.get("/status")
@permission_required("backup:manage")
def status(_user):
    return jsonify(backup_status_payload())


@backup_bp.post("/download")
@permission_required("backup:manage")
def download(user):
    data = request.get_json(silent=True) or {}
    password = data.get("password") or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        return error(f"The backup password must be at least {MIN_PASSWORD_LENGTH} characters long.", 400)

    try:
        encrypted, plain_size = encrypt_backup(password, current_app.config["UPLOAD_DIR"])
    except Exception as exc:  # pragma: no cover - genuine infra failure (pg_dump missing, etc.)
        db.session.add(BackupLog(
            kind="manual_download", user_id=user.id, actor_name_snapshot=user.name,
            success=False, note=str(exc)[:500],
        ))
        db.session.commit()
        current_app.logger.exception("backup download failed")
        return error("Could not build the backup. Check the server log for details.", 500)

    db.session.add(BackupLog(
        kind="manual_download", user_id=user.id, actor_name_snapshot=user.name,
        size_bytes=plain_size,
    ))
    db.session.commit()

    filename = f"backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.lmsbackup"
    return send_file(
        BytesIO(encrypted), as_attachment=True, download_name=filename,
        mimetype="application/octet-stream",
    )
