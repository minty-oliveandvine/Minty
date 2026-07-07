"""Standalone Client Tracker mini-app.

Run:  python tools/client_tracker/tracker_app.py
Then open http://127.0.0.1:5055

- Client column is read LIVE from the real database (pettycashv2.entities.name).
- "Bill activated?" is DERIVED live: entity_function_map.is_enabled for the
  BILL function (with the app's catalog fallback). Read-only.
- "Client input date until" is DERIVED live from the database: the latest
  report_v2.report_date / report_draft.transaction_date the client entered.
  Read-only.
- Only "OV published and checked until" is manually tracked, stored in
  tracker_data.json next to this file, keyed by entity id. No schema changes to
  the main app.
- Reuses the same RDS_DATABASE_URI from the project's .env, so it talks to
  the same database as Minty without booting the whole app.

No authentication: there is no username/password gate. The only protection is
CORS (TRACKER_ALLOWED_ORIGINS) plus keeping the backend URL private. Anyone who
can reach this URL can read the client list and write ov_published_until, so do
NOT expose it on a public/guessable URL.

When you decide where the 3 fields should really live (new table / columns),
only load_tracker()/save_tracker() need to change.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from sqlalchemy import create_engine, text

# Load the project's .env (two levels up from this file).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Prefer a dedicated TRACKER_DATABASE_URI (point this straight at Supabase so
# the tracker sees the live data regardless of any local tunnel). Fall back to
# RDS_DATABASE_URI to match the main app's connection.
DB_URI = os.environ.get("TRACKER_DATABASE_URI") or os.environ.get(
    "RDS_DATABASE_URI"
)
if not DB_URI:
    raise SystemExit(
        "No database URI set. Add TRACKER_DATABASE_URI=<supabase uri> (or "
        "RDS_DATABASE_URI) to the project .env."
    )

# NOTE: This app has NO password gate. It talks to the live database and is
# only shielded by CORS (below) + keeping the backend URL private. Anyone who
# can reach this URL can read the client list and write ov_published_until.

# Comma-separated list of allowed browser origins for CORS. The Vercel frontend
# is on a different domain, so its origin must be listed here (or set
# TRACKER_ALLOWED_ORIGINS="*" to allow any). Example:
#   TRACKER_ALLOWED_ORIGINS=https://client-tracker.vercel.app
_origins_env = os.environ.get("TRACKER_ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

DATA_FILE = Path(__file__).resolve().parent / "tracker_data.json"

engine = create_engine(DB_URI, pool_pre_ping=True)
app = Flask(__name__)


def _cors_origin(request_origin):
    """Return the value to echo in Access-Control-Allow-Origin, or None.

    Echoes the request's Origin only if it's in the allow-list (or the list is
    "*"). Echoing the specific origin — not a literal "*" — is required because
    the frontend sends credentials (the Basic-Auth header); browsers reject
    "*" together with credentials.
    """
    if ALLOWED_ORIGINS == ["*"]:
        return request_origin or "*"
    if request_origin and request_origin in ALLOWED_ORIGINS:
        return request_origin
    return None


@app.after_request
def add_cors_headers(response):
    origin = _cors_origin(request.headers.get("Origin"))
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


@app.route("/api/rows", methods=["OPTIONS"])
@app.route("/api/rows/<entity_id>", methods=["OPTIONS"])
def cors_preflight(entity_id=None):
    """Answer the browser's CORS preflight.

    The after_request hook attaches the actual CORS headers.
    """
    return ("", 204)


def load_tracker():
    """Return {entity_id: {bill_activated, client_input_until, ov_published_until}}."""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text() or "{}")
        except json.JSONDecodeError:
            return {}
    return {}


def save_tracker(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))


def fetch_clients():
    """Live read of client names from the entities table."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name FROM pettycashv2.entities "
                "ORDER BY lower(name)"
            )
        ).fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def fetch_bill_activated():
    """Return {entity_id: bool} — whether the BILL module is activated.

    Mirrors the app's _is_module_enabled logic exactly:
      * a row in entity_function_map for (entity, BILL) -> its is_enabled
      * no row -> fall back to entity_function.is_active for BILL
      * BILL function not in the catalog at all -> default True
    Computed for every entity in one query (LEFT JOIN) so unmapped entities
    still get the correct fallback.
    """
    with engine.connect() as conn:
        fn = conn.execute(
            text(
                "SELECT id, is_active FROM pettycashv2.entity_function "
                "WHERE function_code = 'BILL'"
            )
        ).first()

        # BILL not in the catalog -> every entity defaults to enabled.
        if fn is None:
            return {}

        bill_fn_id, bill_is_active = fn[0], bool(fn[1])
        rows = conn.execute(
            text(
                """
                SELECT e.id,
                       COALESCE(m.is_enabled, :fallback) AS activated
                FROM pettycashv2.entities e
                LEFT JOIN pettycashv2.entity_function_map m
                       ON m.entity_id = e.id
                      AND m.entity_function_id = :fn_id
                """
            ),
            {"fallback": bill_is_active, "fn_id": bill_fn_id},
        ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def fetch_last_input_dates():
    """Return {entity_id: 'YYYY-MM-DD'} of the latest date each client entered
    expense/report data.

    Derived live from the data, not stored: the max of report_v2.report_date
    (submitted reports) and report_draft.transaction_date (in-progress drafts).
    Note report_draft stores the entity id in its `company` column, not
    entity_id. Computed for all entities in one query to avoid N round-trips.
    """
    sql = text(
        """
        SELECT entity_id, MAX(d) AS last_input
        FROM (
            SELECT entity_id, report_date::date AS d
            FROM pettycashv2.report_v2
            WHERE entity_id IS NOT NULL AND report_date IS NOT NULL
            UNION ALL
            SELECT company AS entity_id, transaction_date::date AS d
            FROM pettycashv2.report_draft
            WHERE company IS NOT NULL AND transaction_date IS NOT NULL
        ) entered
        GROUP BY entity_id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return {r[0]: r[1].isoformat() for r in rows if r[1] is not None}


@app.get("/")
def index():
    return PAGE


@app.get("/api/rows")
def api_rows():
    """Merge live client list + derived fields with stored tracker fields.

    bill_activated and client_input_until are DERIVED from the database (not
    editable). Only ov_published_until remains manually tracked in
    tracker_data.json.
    """
    tracker = load_tracker()
    last_input = fetch_last_input_dates()
    bill_active = fetch_bill_activated()
    rows = []
    for c in fetch_clients():
        t = tracker.get(c["id"], {})
        rows.append(
            {
                "id": c["id"],
                "name": c["name"],
                # Default True when the entity isn't in the map AND no catalog
                # fallback applied (BILL function absent) — matches app logic.
                "bill_activated": bill_active.get(c["id"], True),
                "client_input_until": last_input.get(c["id"], ""),
                "ov_published_until": t.get("ov_published_until", ""),
            }
        )
    # Latest "client input date until" first; clients with no input date
    # (empty string) sort to the bottom. ISO YYYY-MM-DD strings sort
    # correctly as text, so a reverse string sort = newest first.
    rows.sort(key=lambda r: r["client_input_until"] or "", reverse=True)
    return jsonify(rows)


@app.post("/api/rows/<entity_id>")
def api_save(entity_id):
    """Upsert the manually-tracked field for one client.

    bill_activated and client_input_until are NOT saved here — both are derived
    from the database in api_rows(). Only ov_published_until is user-editable.
    """
    payload = request.get_json(silent=True) or {}
    tracker = load_tracker()
    tracker[entity_id] = {
        "ov_published_until": (payload.get("ov_published_until") or "").strip(),
    }
    save_tracker(tracker)
    return jsonify({"status": "ok"})


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Client Tracker</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; margin: 32px; color: #1a1a1a; }
  h1 { font-size: 20px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; }
  th { background: #f4f4f5; font-weight: 600; }
  tr:nth-child(even) td { background: #fafafa; }
  input[type=date] { font: inherit; padding: 3px; }
  .saved { color: #16a34a; font-size: 12px; visibility: hidden; }
  .saved.show { visibility: visible; }
  td.derived { color: #374151; font-variant-numeric: tabular-nums; }
  .none { color: #9ca3af; }
  .yes { color: #16a34a; font-weight: 600; }
  .no { color: #b91c1c; font-weight: 600; }
  #status { color: #6b7280; font-size: 13px; margin-bottom: 12px; }
</style>
</head>
<body>
  <h1>Client Tracker</h1>
  <div id="status">Loading…</div>
  <table>
    <thead>
      <tr>
        <th>Client</th>
        <th>Bill activated?</th>
        <th>Client input date until</th>
        <th>OV published and checked until</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

<script>
async function load() {
  const res = await fetch('/api/rows');
  const rows = await res.json();
  const tbody = document.getElementById('rows');
  tbody.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(r.name)}</td>
      <td class="derived">${r.bill_activated
          ? '<span class="yes">Yes</span>' : '<span class="no">No</span>'}</td>
      <td class="derived">${r.client_input_until || '<span class="none">—</span>'}</td>
      <td><input type="date" value="${r.ov_published_until || ''}" data-f="ov_published_until"></td>
      <td><span class="saved">saved ✓</span></td>`;
    tr.querySelectorAll('input').forEach(inp =>
      inp.addEventListener('change', () => save(r.id, tr)));
    tbody.appendChild(tr);
  }
  document.getElementById('status').textContent =
    rows.length + ' clients · bill status + input date live from the database';
}

async function save(id, tr) {
  const body = {
    ov_published_until: tr.querySelector('[data-f=ov_published_until]').value,
  };
  await fetch('/api/rows/' + encodeURIComponent(id), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const badge = tr.querySelector('.saved');
  badge.classList.add('show');
  setTimeout(() => badge.classList.remove('show'), 1200);
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    # Bind to 0.0.0.0 so a tunnel (cloudflared/ngrok) can forward to it.
    # debug=False: never expose the Werkzeug debugger on a shared link.
    app.run(host="0.0.0.0", port=5055, debug=False)
