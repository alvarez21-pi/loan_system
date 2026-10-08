"""One-time command: PROVE a downloaded backup actually restores, without
ever touching the real database.

What it does:
  1. Decrypts the backup file you give it (same password you chose when
     downloading it from the Backup page).
  2. Creates a brand-new, disposable Postgres database on the SAME
     server as DATABASE_URL — named lms_restore_test_<random> — never
     the real database. Creating/dropping a database is a server-level
     command; the connection used to issue it never reads or writes a
     single row of the real database's data.
  3. Restores the backup's SQL dump into THAT throwaway database only.
  4. Prints every table's row count, so you can see the restore actually
     produced real data (and not, say, an empty schema).
  5. Drops the throwaway database again — nothing is left behind, on the
     server or on disk.

It needs the same Postgres server DATABASE_URL already points at (CREATE
DATABASE/DROP DATABASE privileges on it — the same user docker-compose
already configures has this), and the `psql` client on PATH (already
true inside the backend container).

Usage (from the project root):
    docker compose exec backend python scripts/test_restore_backup.py \\
        /path/to/backup-20261014-020000.lmsbackup

The backup's password is read from the BACKUP_PASSWORD environment
variable if set, or prompted for interactively (never as a CLI argument
— that would leak into shell history and `ps`/process listings).
"""
import argparse
import getpass
import os
import sys
import tempfile
import uuid
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def throwaway_url(real_url, database_name):
    """Same server/user/password as `real_url`, different database name."""
    parts = urlsplit(real_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", "", ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backup_file", help="path to the .lmsbackup file to test")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.backup_file):
        raise SystemExit(f"no such file: {args.backup_file}")

    real_url = os.environ.get("DATABASE_URL", "")
    if real_url.startswith("sqlite"):
        raise SystemExit(
            "this check is for a real Postgres deployment — DATABASE_URL is "
            "sqlite here (local/dev setup), nothing to safely test against"
        )

    password = os.getenv("BACKUP_PASSWORD") or getpass.getpass("Backup password: ")
    if not password:
        raise SystemExit("a password is required to decrypt the backup")

    import psycopg2

    from services.backup import decrypt_backup, extract_backup_zip, restore_database

    with open(args.backup_file, "rb") as f:
        encrypted = f.read()

    print("Decrypting...")
    try:
        plain_zip = decrypt_backup(encrypted, password)
    except ValueError as exc:
        raise SystemExit(str(exc))

    db_name = f"lms_restore_test_{uuid.uuid4().hex[:8]}"
    test_url = throwaway_url(real_url, db_name)

    print(f"Creating throwaway database {db_name!r} (the real database is never touched)...")
    admin_conn = psycopg2.connect(real_url)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    admin_conn.close()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            print("Extracting...")
            dump_path, _uploads_dir = extract_backup_zip(plain_zip, tmp)
            if dump_path is None:
                raise SystemExit("this backup does not contain a recognizable database dump")

            print(f"Restoring into {db_name!r}...")
            restore_database(dump_path, url=test_url)
            print("Restore complete. Row counts:\n")

            conn = psycopg2.connect(test_url)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name"
                    )
                    tables = [row[0] for row in cur.fetchall()]
                    for table in tables:
                        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                        count = cur.fetchone()[0]
                        print(f"  {table:<30} {count}")
            finally:
                conn.close()
    finally:
        print(f"\nDropping throwaway database {db_name!r}...")
        admin_conn = psycopg2.connect(real_url)
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin_conn.close()

    print("Done. The real database was never opened for writing.")


if __name__ == "__main__":
    main()
