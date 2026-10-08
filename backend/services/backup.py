"""Phase 6: encrypted backup/restore.

A CEO/head_manager's interactive download (routes/backup.py) types a
password at download time. That password derives an AES-256-GCM key via
PBKDF2 — it is never stored or logged anywhere, only held in-process for
the one request that uses it. The nightly server-side backup
(write_nightly_backup, called from services/scheduler.py) writes an
UNENCRYPTED copy instead: there is no one present to type a password for
an unattended job, and holding a static server-side key to encrypt it
automatically would just relocate the secret into the deployment's own
config rather than protect it. That copy is protected by the container/
volume's own access control instead; the interactive download is
protected by a password because that file actually leaves the server.

Uses `pycryptodome` (already a dependency — see requirements.txt) for
AES-256-GCM and PBKDF2. No new dependency was added for this.
"""
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from io import BytesIO

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

PBKDF2_ITERATIONS = 310_000
SALT_BYTES = 16
NONCE_BYTES = 16
TAG_BYTES = 16
KEY_BYTES = 32  # AES-256

NIGHTLY_PREFIX = "backup-"
NIGHTLY_SUFFIX = ".zip"


def dump_database_bytes():
    """Returns (dump_bytes, archive_name) for whatever database this
    process is actually configured against — Postgres in every real
    deployment, sqlite in tests (and only tests: docker-compose never
    configures sqlite). Dumping over the sqlite file's own bytes is a
    complete, correct backup of it; there's no separate dump tool needed
    the way there is for Postgres.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite"):
        path = url.split("sqlite:///", 1)[-1]
        with open(path, "rb") as f:
            return f.read(), "database.sqlite3"

    # --clean --if-exists: the dump includes DROP ... IF EXISTS before each
    # CREATE, so restoring it onto a database that already has a (possibly
    # corrupted) copy of the same schema replaces it cleanly rather than
    # failing on "relation already exists" — the normal disaster-recovery
    # shape for a plain-SQL pg_dump.
    result = subprocess.run(
        ["pg_dump", "--no-owner", "--no-acl", "--clean", "--if-exists", url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout, "database.sql"


def _build_zip(upload_dir):
    """The plain (unencrypted) zip: the database dump plus every file under
    upload_dir, entirely in memory — this app's borrower-photo/ID-document
    uploads are nowhere near large enough to need a streaming approach."""
    dump_bytes, dump_name = dump_database_bytes()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(dump_name, dump_bytes)
        if upload_dir and os.path.isdir(upload_dir):
            for root, _dirs, files in os.walk(upload_dir):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.join("uploads", os.path.relpath(full, upload_dir))
                    zf.write(full, arcname=rel)
    return buffer.getvalue()


def _derive_key(password, salt):
    return PBKDF2(password.encode("utf-8"), salt, dkLen=KEY_BYTES, count=PBKDF2_ITERATIONS, hmac_hash_module=SHA256)


def encrypt_backup(password, upload_dir):
    """Returns (encrypted_bytes, plain_size_bytes). Format on disk: salt
    (16) || nonce (16) || tag (16) || ciphertext. GCM's tag means a wrong
    password or a corrupted/tampered file is detected immediately on
    decrypt, not silently accepted as garbage."""
    plain = _build_zip(upload_dir)
    salt = get_random_bytes(SALT_BYTES)
    key = _derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=get_random_bytes(NONCE_BYTES))
    ciphertext, tag = cipher.encrypt_and_digest(plain)
    return salt + cipher.nonce + tag + ciphertext, len(plain)


def decrypt_backup(data, password):
    """Reverses encrypt_backup(); raises ValueError on a wrong password or
    a corrupted/tampered file (the GCM tag simply won't verify)."""
    header = SALT_BYTES + NONCE_BYTES + TAG_BYTES
    if len(data) < header:
        raise ValueError("This file is too short to be a valid backup.")
    salt, nonce, tag, ciphertext = (
        data[:SALT_BYTES],
        data[SALT_BYTES:SALT_BYTES + NONCE_BYTES],
        data[SALT_BYTES + NONCE_BYTES:header],
        data[header:],
    )
    key = _derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError:
        raise ValueError("Incorrect password, or this file is corrupted.")


def write_nightly_backup(backup_dir, upload_dir, keep_days=14):
    """Writes an unencrypted dated zip to backup_dir, then deletes any
    nightly backup older than keep_days. Returns (filename, size_bytes)."""
    os.makedirs(backup_dir, exist_ok=True)
    data = _build_zip(upload_dir)
    filename = f"{NIGHTLY_PREFIX}{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}{NIGHTLY_SUFFIX}"
    with open(os.path.join(backup_dir, filename), "wb") as f:
        f.write(data)
    prune_old_backups(backup_dir, keep_days)
    return filename, len(data)


def prune_old_backups(backup_dir, keep_days=14):
    if not os.path.isdir(backup_dir):
        return
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    for name in os.listdir(backup_dir):
        if not (name.startswith(NIGHTLY_PREFIX) and name.endswith(NIGHTLY_SUFFIX)):
            continue
        path = os.path.join(backup_dir, name)
        if os.path.isfile(path) and datetime.utcfromtimestamp(os.path.getmtime(path)) < cutoff:
            os.remove(path)


def extract_backup_zip(zip_bytes, dest_dir):
    """Extracts a decrypted backup zip into dest_dir. Returns
    (dump_path, uploads_dir_or_None)."""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        zf.extractall(dest_dir)
    dump_path = None
    for candidate in ("database.sql", "database.sqlite3"):
        path = os.path.join(dest_dir, candidate)
        if os.path.isfile(path):
            dump_path = path
            break
    uploads_dir = os.path.join(dest_dir, "uploads")
    return dump_path, (uploads_dir if os.path.isdir(uploads_dir) else None)


def restore_database(dump_path, url=None):
    """Restores dump_path into the database `url` points at — the mirror
    image of dump_database_bytes(). Defaults to DATABASE_URL (the real,
    normal restore path); scripts/test_restore_backup.py passes an
    explicit THROWAWAY url instead, so it never touches the real one."""
    url = url if url is not None else os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite"):
        path = url.split("sqlite:///", 1)[-1]
        shutil.copyfile(dump_path, path)
        return
    result = subprocess.run(
        ["psql", url, "-v", "ON_ERROR_STOP=1", "-f", dump_path],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql restore failed: {result.stderr.decode(errors='replace').strip()}")


def restore_uploads(extracted_uploads_dir, upload_dir):
    """Replaces upload_dir's contents with extracted_uploads_dir's. The
    existing directory is removed first so a restore doesn't leave behind
    files that were deleted after the backup was taken."""
    if extracted_uploads_dir is None:
        return
    if os.path.isdir(upload_dir):
        shutil.rmtree(upload_dir)
    shutil.copytree(extracted_uploads_dir, upload_dir)
