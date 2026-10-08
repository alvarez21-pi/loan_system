FROM python:3.11-slim
WORKDIR /app

# Phase 6: pg_dump/psql for the Backup page and scripts/restore_backup.py.
# Pinned to major version 15 — matching docker-compose's `postgres:15` —
# via the official PGDG repo, not Debian's own default `postgresql-client`
# package. This was tested, not assumed: Debian trixie's default package
# resolves to v18, whose pg_dump writes a `SET transaction_timeout = 0;`
# preamble line (a setting that only exists on a v17+ SERVER); restoring
# that dump onto a v15 server — the exact server this stack runs — then
# fails outright with "unrecognized configuration parameter". Pinning the
# client to the server's own major version avoids that whole class of
# version-skew failure.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-15 \
    && ln -sf /usr/lib/postgresql/15/bin/pg_dump /usr/local/bin/pg_dump \
    && ln -sf /usr/lib/postgresql/15/bin/psql /usr/local/bin/psql \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Phase 2 item 1: gunicorn, never the Werkzeug dev server (app.run()) —
# `app:app` is only ever imported here, so create_app()'s startup-safety
# checks (services/startup_safety.py) still run exactly once, and the
# Werkzeug interactive debugger is structurally unreachable under gunicorn
# regardless of app.debug (Flask only wraps the debugger middleware around
# app.run()'s own dev server, never around an externally-served WSGI app).
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "app:app"]