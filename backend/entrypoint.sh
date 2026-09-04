#!/bin/sh
# One entrypoint, four roles.  Migrations only ever run in the `migrate` role,
# and Alembic itself holds a Postgres advisory lock (see migrations/env.py), so a
# stray invocation cannot race a running one.
set -eu

ROLE="${1:-api}"

wait_for_db() {
  echo "waiting for postgres..."
  for _ in $(seq 1 60); do
    if python - <<'PY'
import sys
import psycopg
from app.config.settings import settings
try:
    with psycopg.connect(settings.DATABASE_URL_SYNC.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=2):
        sys.exit(0)
except Exception:
    sys.exit(1)
PY
    then
      echo "postgres ready"
      return 0
    fi
    sleep 1
  done
  echo "postgres did not become ready" >&2
  return 1
}

case "$ROLE" in
  migrate)
    wait_for_db
    alembic upgrade head
    echo "migrations applied"
    ;;
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
    ;;
  api-reload)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers
    ;;
  worker)
    exec python -m app.worker
    ;;
  relay)
    exec python -m app.relay
    ;;
  seed)
    wait_for_db
    exec python -m scripts.seed
    ;;
  *)
    exec "$@"
    ;;
esac
