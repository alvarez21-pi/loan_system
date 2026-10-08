"""Restore an encrypted backup produced by the Backup page (Phase 6) —
overwrites the database this process is configured against (DATABASE_URL)
and, if the backup contains one, replaces the uploads directory.

This is destructive by design (that is the point of a restore) and is
therefore hard to run by accident:
- --yes must be passed explicitly on the command line.
- The backup's password is read from the BACKUP_PASSWORD environment
  variable if set, or prompted for interactively (never as a CLI
  argument — that would leak into shell history and `ps`/process
  listings).

Typical use, exec'd into the running backend container:
    docker compose exec backend python scripts/restore_backup.py \\
        /path/to/backup-20261014-020000.lmsbackup --yes
"""
import argparse
import getpass
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backup_file", help="path to the .lmsbackup file to restore")
    parser.add_argument(
        "--yes", action="store_true",
        help="confirm this OVERWRITES the current database (and uploads, if the backup has any) — required, no default",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.backup_file):
        raise SystemExit(f"no such file: {args.backup_file}")
    if not args.yes:
        raise SystemExit(
            "refusing to run: pass --yes to confirm this OVERWRITES the current "
            "database and uploads directory with the backup's contents"
        )

    password = os.getenv("BACKUP_PASSWORD") or getpass.getpass("Backup password: ")
    if not password:
        raise SystemExit("a password is required to decrypt the backup")

    from app import create_app
    from services.backup import decrypt_backup, extract_backup_zip, restore_database, restore_uploads

    with open(args.backup_file, "rb") as f:
        encrypted = f.read()

    print("Decrypting...")
    try:
        plain_zip = decrypt_backup(encrypted, password)
    except ValueError as exc:
        raise SystemExit(str(exc))

    app = create_app()
    with app.app_context():
        with tempfile.TemporaryDirectory() as tmp:
            print("Extracting...")
            dump_path, uploads_dir = extract_backup_zip(plain_zip, tmp)
            if dump_path is None:
                raise SystemExit("this backup does not contain a recognizable database dump")

            print("Restoring the database — this OVERWRITES the current one...")
            restore_database(dump_path)
            print("Database restored.")

            if uploads_dir is not None:
                print("Restoring uploads — this REPLACES the current uploads directory...")
                restore_uploads(uploads_dir, app.config["UPLOAD_DIR"])
                print("Uploads restored.")
            else:
                print("This backup has no uploads directory — nothing to restore there.")

    print("Restore complete.")


if __name__ == "__main__":
    main()
