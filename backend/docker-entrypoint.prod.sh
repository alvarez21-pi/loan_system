#!/bin/sh
# Migrate -> idempotent CEO seed -> serve. Used by docker-compose.prod.yml
# (Coolify) and by docker-compose.override.yml (local `docker compose up`)
# — both need this to run unattended, with nothing to exec into the
# container for by hand. The plain docker-compose.yml on its own (no
# override) still does NOT use this; see DEPLOYMENT.md for that manual
# procedure. Order matters: migrate the schema BEFORE the idempotent CEO
# seed runs against it (seed_ceo.py assumes the schema already matches
# the current models), and only start serving requests once both are done.
set -e

echo "[entrypoint] running database migrations..."
flask db upgrade

echo "[entrypoint] seeding CEO account (idempotent)..."
python seed_ceo.py

echo "[entrypoint] starting gunicorn..."
exec gunicorn --workers 2 --bind 0.0.0.0:5000 app:app
