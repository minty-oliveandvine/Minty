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
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS pettycashv3"))
    conn.commit()
PY

echo "Initializing database schema and running migrations..."
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  # Run the migration against a non-database session backend.
  #
  # Flask-Session's sqlalchemy backend creates its `sessions` table the moment
  # the app is imported (`__table__.create(checkfirst=True)`), and `flask db
  # upgrade` imports the app before Alembic runs. On a cold database that means
  # `sessions` already exists by the time 0001_full_schema tries to create it,
  # and the whole upgrade dies with DuplicateTable. Swapping the backend for
  # this one command keeps Alembic the sole creator of the tables it declares;
  # the served app below still uses the database-backed sessions.
  #
  # `cachelib` with no configured client falls back to a FileSystemCache in
  # ./flask_session, and in development /app is bind-mounted from the host — so
  # clear it out rather than leaving a stray directory in someone's checkout.
  SESSION_TYPE=cachelib python -m flask --app main.py db upgrade
  rm -rf ./flask_session
fi

echo "Starting application command: $*"
exec "$@"