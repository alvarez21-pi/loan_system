# Deployment

This file was started by Phase 7 (test environment mode) with just the
reset-script procedure. Phase 6 extends it below with the production
Coolify deployment, the environment-variable checklist, and backup/
restore/rollback. Nothing in the Phase 7 section below changed.

## Resetting a test/staging environment's data

`backend/scripts/reset_dev_data.py` wipes **every user and business
record** in the database it's pointed at, then reseeds a single fresh CEO
account from `CEO_NAME`/`CEO_EMAIL`/`CEO_PASSWORD`. It is deliberately
hard to run by accident:

1. It refuses outright if `ENVIRONMENT=production`, no matter what else
   is set.
2. It refuses unless `ENVIRONMENT_LABEL` is set in the environment — the
   same variable that puts the visible "Test environment"-style banner on
   every page. If the deployment you're pointed at isn't showing that
   banner, the script won't touch its data.
3. It refuses unless you pass `--yes` explicitly on the command line —
   no environment variable can substitute for this.

### To run it safely on a server

1. Confirm you are pointed at the right deployment: open the app in a
   browser and confirm the banner is showing, with the text you expect
   (e.g. "Test environment"). **If there is no banner, stop — do not
   proceed; `ENVIRONMENT_LABEL` is not set there, which the script itself
   will also refuse on, but visually confirming first is the point of
   the banner.**
2. Exec into the running backend container (adjust the service name to
   whatever your compose file/Coolify deployment calls it):
   ```sh
   docker compose exec backend python scripts/reset_dev_data.py --yes
   ```
3. The script prints `wiped: all users and business data` followed by
   `seed_ceo.py`'s own output confirming the fresh CEO account. Sign in
   with the `CEO_PASSWORD` currently set in that environment's `.env` —
   the CEO is forced to change it on first login
   (`must_change_password`), same as any fresh CEO seed.

### Seeding demo/test accounts (local development only)

`backend/scripts/seed_demo_users.py` refuses to run unless
`ALLOW_DEMO_SEED=true` is set in the environment — a dedicated opt-in
flag, not `ENVIRONMENT`/`ENVIRONMENT_LABEL` (both are deliberately
identical between local and a real deployment now, so neither can tell
the two apart any more; see `.env.example`). It is set in the local
`.env.example` only, never in `docker-compose.prod.yml`, so the script
structurally cannot run against a real deployment. Run it locally (no
need to run `reset_dev_data.py` first — it's safe to run on its own, and
safe to run twice) to get one account per role, a spare Maker for
rate-limit testing, and two fake borrowers, all with a known shared
password printed at the end:
```sh
docker compose exec backend python scripts/seed_demo_users.py
```

## Production deployment (Coolify)

`docker-compose.prod.yml` is the file Coolify deploys — it is a
**separate file** from `docker-compose.yml` (which stays the local/dev
file; nothing about local development changed). The two differ in three
ways, each there for a reason:

1. No service publishes a host port (`ports:`) — Coolify's own proxy
   terminates HTTPS and reaches the one public service over its internal
   Docker network, not through a published port on the host.
2. The backend's startup command runs migrations and the idempotent CEO
   seed before it starts serving requests (`docker-entrypoint.prod.sh`) —
   unattended, since nobody exec's into a Coolify-managed container by
   hand on every deploy the way the "resetting a test environment"
   procedure above assumes.
3. `ENVIRONMENT` and `FLASK_DEBUG` are fixed in the compose file itself
   (`production` / `false`), not read from a variable — debug mode is not
   a configurable property of a production deployment.

### Which service gets the domain

In Coolify, attach your domain to the **`frontend` service, port 3000**.
That is the only service this file exposes at all (`expose: ["3000"]`,
not `ports:`) — the backend, database and email service are reachable
only from other containers on the same compose network, never from
outside it. The frontend's own server proxies `/api/*` to
`http://backend:5000` internally (same mechanism the dev compose file
already uses — see `ARCHITECTURE.md` §7); the browser never talks to the
backend directly.

### Environment variables to set in Coolify

Set these in Coolify's "Environment Variables" panel for the stack — not
in any committed file. `.env.example` at the repo root documents the same
list (it is the one file both compose files read from locally); nothing
below duplicates it, this is that same list organized as a checklist with
exactly how to generate each secret.

| Variable | Required | How to set it |
|---|---|---|
| `POSTGRES_DB` | optional (defaults `loan_system`) | a plain name, no secret |
| `POSTGRES_USER` | optional (defaults `loanuser`) | a plain name, no secret |
| `POSTGRES_PASSWORD` | **required** | generate: `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `JWT_SECRET_KEY` | **required**, 32+ bytes | generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `EMAIL_SERVICE_SECRET` | **required**, 32+ bytes | generate the same way as `JWT_SECRET_KEY` — a different value, shared only between the `backend` and `email-service` containers |
| `FRONTEND_URL` | **required** | the real `https://` domain you're about to attach to `frontend` in Coolify (used to build links in emails — set it to match, not `localhost`) |
| `LOGO_URL` | optional | set to `${FRONTEND_URL}/logo.png` (your real domain) in Coolify's environment variables so the logo in emails is a plain image link, not an attachment — leave unset and the logo falls back to being embedded inline instead |
| `CEO_NAME` | **required** | the actual CEO's name — not a placeholder |
| `CEO_EMAIL` | **required** | the actual CEO's email |
| `CEO_PASSWORD` | **required**, 12+ chars | a strong password of your choosing — the CEO is forced to change it on first login regardless |
| `CEO_PHONE` | optional (defaults `255700000000`) | the actual CEO's phone, if you want it seeded correctly from the start |
| `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_PORT` / `SMTP_ENCRYPTION` | required for email to actually send | your real mail provider's credentials — `SMTP_PASSWORD` is a secret, treat it like one |
| `FROM_EMAIL` / `FROM_NAME` | required for email to actually send | the address/name recipients see |
| `USER_DELETION_RETENTION_DAYS` | optional (defaults 30) | plain number, no secret |
| `VERIFICATION_TOKEN_TTL_HOURS` / `PASSWORD_RESET_TTL_MINUTES` | optional | plain numbers, no secret |
| `BACKUP_RETENTION_DAYS` | optional (defaults 14) | plain number, no secret — how many days of *nightly* server-side backups to keep |
| `ENVIRONMENT_LABEL` | leave **unset** on real production | only set this if you are deploying a staging copy through Coolify too (Phase 7) — it puts a visible banner on every page and is what gates `reset_dev_data.py` |

No real value for any of the above belongs in any committed file,
including this one — the table above says how to generate each secret,
never what to set it to.

### Health checks

- `GET /api/health` returns `503` if the backend can't reach the
  database (it runs `SELECT 1`), not just whether the Python process is
  up — Coolify (or any orchestrator) should restart a backend that can't
  reach its database, not keep routing traffic to it.
- `db` uses `pg_isready`; `email-service` and `frontend` each have their
  own HTTP-reachability check. All four have `restart: unless-stopped`.

### Rollback

A deploy is a new set of images built from a given commit; rolling back
means redeploying the previous commit's images in Coolify (its "Redeploy"
on an earlier deployment, or re-triggering a deploy after reverting the
branch). Two things to know before you do:

- **Migrations are forward-only.** `docker-entrypoint.prod.sh` runs
  `flask db upgrade` on every start, including after a rollback — it does
  **not** run `flask db downgrade`. If the commit you're rolling back to
  predates a migration that already ran, the old code will be running
  against a newer schema than it expects. For a schema change that
  shipped in the same deploy you're rolling back, check whether that
  migration is safe to leave applied (an added nullable column usually
  is) or needs a manual `flask db downgrade <revision>` exec'd into the
  container first.
- **Restoring a backup is the other half of a real rollback** (bad data,
  not just bad code) — see below.

## Backups

### What gets backed up, and how

- **Interactive download** (Backup page, CEO/head_manager only): a full
  `pg_dump` of the database plus every file under the uploads volume,
  zipped and then encrypted with AES-256-GCM using a password you type
  at download time. That password is **never stored or logged anywhere**
  — it exists only in that one request, used to derive the encryption
  key, and then it's gone. There is no way to recover a lost password;
  write it down somewhere safe, separate from the file itself.
- **Nightly server-side backup** (`services/scheduler.py`, 2am): the same
  dump+uploads zip, but **unencrypted**, written to the `backups` named
  volume and kept for `BACKUP_RETENTION_DAYS` (default 14). There is no
  password for this one because there is no one present to type one for
  an unattended job — it's protected by the container/volume's own access
  control instead. This protects against local disk/database corruption
  between your own downloads; it never leaves the server, so it is not a
  substitute for actually downloading one.
- The Backup page shows when each kind last happened, and the dashboard
  shows a warning banner once it's been more than 7 days since the last
  **interactive** download — the nightly job running on schedule doesn't
  clear that warning, because the point of the warning is "has anyone
  actually taken a copy off this server."

### Restoring a backup

```sh
# Exec into the running backend container:
docker compose -f docker-compose.prod.yml exec backend \
  python scripts/restore_backup.py /path/to/backup-20261014-020000.lmsbackup --yes
```

- You'll be prompted for the backup's password (or set `BACKUP_PASSWORD`
  in the shell you're running this from, never as a command-line
  argument — that would leak into shell history).
- This **overwrites** the current database and, if the backup has one,
  **replaces** the entire uploads directory. `--yes` is required — there
  is no default.
- A wrong password fails immediately with a clear error (AES-GCM's
  authentication tag won't verify) — it never silently restores garbage.
- To restore the *nightly* (unencrypted) backups instead, the same
  `restore_backup.py` script doesn't apply directly — they're plain zips,
  not `.lmsbackup` files. Unzip one manually and apply `database.sql`
  with `psql $DATABASE_URL -f database.sql`, then copy its `uploads/`
  over the uploads volume by hand; this is the documented disaster path
  for that copy, deliberately a manual, careful procedure rather than a
  one-command script, since it's the backup you'd reach for when
  something has already gone wrong with the encrypted one.

### Testing a restore (do this periodically, not just when you need it)

A backup you have never restored is unverified. One command proves it —
decrypts the file, creates a brand-new throwaway database **on the same
Postgres server** (never the real database — creating/dropping a
database is a server-level command, it never reads or writes a row of
real data), restores into it, prints every table's row count, then drops
the throwaway database again:

```sh
docker compose -f docker-compose.prod.yml exec \
  backend python scripts/test_restore_backup.py /path/to/the/backup.lmsbackup
```

You'll be prompted for the backup's password (or set `BACKUP_PASSWORD`
in the shell, never as a command-line argument). Do this on some regular
cadence (e.g. whenever you rotate the CEO's backup password, or monthly)
— a printed row count on every table you expect data in is the proof the
backup actually works, not just that the download succeeded.

This exact procedure (decrypt → extract → restore into a fresh,
empty Postgres 15 database → verify the data round-tripped correctly)
was run once already while building this feature, against a throwaway
Postgres 15 container, confirming the backup/restore scripts genuinely
work end-to-end — that test found and fixed a `pg_dump`/server version
mismatch.
