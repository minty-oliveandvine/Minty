#!/usr/bin/env sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  echo "Missing DATABASE_URL (postgresql://user:pass@host:5432/dbname?schema=pettycashv3)."
  exit 1
fi

python - <<'PY'
import os
import time

from sqlalchemy import create_engine, text

# The same parser the app uses: `?schema=` is popped off (default pettycashv3) and
# never reaches the driver; every other query parameter (sslmode, ...) stays.
from services.app_runtime.env import database_schema, database_url

db_uri = database_url()
schema = database_schema()

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
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
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
