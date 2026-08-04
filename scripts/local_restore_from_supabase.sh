#!/usr/bin/env bash
#
# Rehearse the production migration locally.
#
#   1. dump the pettycashv2 schema from Supabase   (READ ONLY)
#   2. drop the local schema and restore the dump  (LOCAL ONLY)
#   3. run flask db upgrade against LOCAL          (LOCAL ONLY)
#
# This is the closest thing to a production dry run: the migrations meet real
# data, so the pre-flight checks (P1/P2/P3/P4 in r10a10) get exercised for the
# first time against rows that actually exist.
#
# ---------------------------------------------------------------------------
# THE SAFETY RULE THIS SCRIPT ENFORCES
#
# The app and `flask db upgrade` both read RDS_DATABASE_URI. If that ever
# points at Supabase while a migration runs, r10a10 DROPS SEVEN PRODUCTION
# TABLES. So:
#
#   * the Supabase URL is passed as an argument and used ONLY by pg_dump
#   * RDS_DATABASE_URI is never read from, written to, or exported here
#   * the script refuses to run if RDS_DATABASE_URI is not localhost
#
# ---------------------------------------------------------------------------
# USAGE
#
#   bash scripts/local_restore_from_supabase.sh "postgresql://USER:PW@HOST:5432/postgres"
#
# Get that string from Supabase -> Project Settings -> Database -> Connection
# string -> URI. Use the SESSION (port 5432) pooler, not the transaction one —
# pg_dump needs a real session.
#
set -euo pipefail

SUPABASE_URL="${1:-}"
RUN_UPGRADE=1
for arg in "$@"; do
    if [[ "$arg" == "--no-upgrade" ]]; then RUN_UPGRADE=0; fi
done
if [[ -z "$SUPABASE_URL" ]]; then
    echo "ERROR: pass the Supabase connection string as argument 1." >&2
    echo "  bash $0 \"postgresql://user:pw@host:5432/postgres\"" >&2
    exit 1
fi

if [[ "$SUPABASE_URL" == *localhost* || "$SUPABASE_URL" == *127.0.0.1* ]]; then
    echo "ERROR: that looks like your LOCAL database, not Supabase." >&2
    exit 1
fi

# --- guard: the app's URI must be local -----------------------------------
LOCAL_URL="$(python - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv(".env")
print(os.environ.get("RDS_DATABASE_URI", ""))
PY
)"
if [[ -z "$LOCAL_URL" ]]; then
    echo "ERROR: RDS_DATABASE_URI is not set in .env" >&2
    exit 1
fi
if [[ "$LOCAL_URL" != *localhost* && "$LOCAL_URL" != *127.0.0.1* ]]; then
    echo "ERROR: RDS_DATABASE_URI does NOT point at localhost." >&2
    echo "       It is: ${LOCAL_URL//:*@/:<redacted>@}" >&2
    echo "       Point it back at your local database before running this," >&2
    echo "       or flask db upgrade will migrate whatever it names." >&2
    exit 1
fi
echo "OK: RDS_DATABASE_URI is local. flask db upgrade cannot reach production."

STAMP="$(python -c "import time; print(time.strftime('%Y%m%d_%H%M%S'))")"
DUMP="prod_${STAMP}.dump"
SAFETY="local_before_restore_${STAMP}.dump"

# --- 0. snapshot the CURRENT local db, so this is undoable -----------------
echo
echo "== 0/4  snapshotting current local schema -> ${SAFETY}"
pg_dump "$LOCAL_URL" -n pettycashv2 -Fc -f "$SAFETY"
echo "   done ($(wc -c < "$SAFETY") bytes)"

# --- 1. dump production (READ ONLY) ---------------------------------------
echo
echo "== 1/4  dumping pettycashv2 from Supabase -> ${DUMP}   (read only)"
pg_dump "$SUPABASE_URL" -n pettycashv2 -Fc --no-owner --no-acl -f "$DUMP"
echo "   done ($(wc -c < "$DUMP") bytes)"

# --- 2. replace the local schema ------------------------------------------
echo
echo "== 2/4  dropping + restoring local pettycashv2"
psql "$LOCAL_URL" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS pettycashv2 CASCADE;'
pg_restore -d "$LOCAL_URL" --no-owner --no-acl "$DUMP"
echo "   restored"

# --- 3. what version did production leave it at? --------------------------
echo
echo "== 3/4  version restored from production:"
psql "$LOCAL_URL" -At -c 'SELECT version_num FROM pettycashv2.alembic_version;' \
    | sed 's/^/   /'
echo "   tables: $(psql "$LOCAL_URL" -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='pettycashv2' AND table_type='BASE TABLE';")"

# --- 4. migrate LOCAL ------------------------------------------------------
if [[ "$RUN_UPGRADE" -eq 0 ]]; then
    echo
    echo "== 4/4  SKIPPED (--no-upgrade)"
    echo "   Local now matches production exactly, un-migrated."
    echo "   Run 'flask db upgrade' yourself when you are ready."
else
    echo
    echo "== 4/4  running flask db upgrade against LOCAL"
    echo "   watch the P1/P2/P3/P4 lines — this is the real pre-flight test"
    echo
    flask db upgrade
fi

echo
echo "=========================================================="
echo "Done. Final state:"
flask db current 2>&1 | grep -v '^INFO' | sed 's/^/   /'
psql "$LOCAL_URL" -At -c "
  SELECT '   legacy tables left: ' || COALESCE(string_agg(table_name, ', '), 'NONE')
    FROM information_schema.tables
   WHERE table_schema='pettycashv2'
     AND table_name IN ('report_draft','shop_expense_draft','report_cashcount_draft',
                        'report_history_draft','report_detail','report_expense_detail',
                        'report_v2','report_cash_detail','report_history_v2');"
echo
echo "To undo:  pg_restore -d \"\$LOCAL_URL\" --clean --if-exists ${SAFETY}"
echo "=========================================================="
