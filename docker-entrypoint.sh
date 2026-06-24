#!/usr/bin/env sh
set -eu

DB_URI="${LOCAL_DATABASE_URI:-${RDS_DATABASE_URI:-}}"
if [ -z "$DB_URI" ]; then
  echo "Missing LOCAL_DATABASE_URI and RDS_DATABASE_URI."
  exit 1
fi

export DB_URI

python - <<'PY'
import os
import time
from sqlalchemy import create_engine, text


db_uri = os.environ["DB_URI"]

wait_seconds = int(os.environ.get("DB_WAIT_SECONDS", "60"))

for attempt in range(1, wait_seconds + 1):
    try:
        engine = create_engine(db_uri)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        break
    except Exception as exc:
        if attempt >= wait_seconds:
            raise RuntimeError(f"Database not ready after {wait_seconds} attempts: {exc}")
        time.sleep(2)

with engine.connect() as conn:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS pettycashv2"))
    conn.commit()
PY

echo "Initializing database schema and running migrations..."
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  python -m flask --app main.py db upgrade
fi

echo "Starting application command: $*"
exec "$@"