#!/usr/bin/env bash
#
# Launch the Client Tracker app + a Cloudflare tunnel that gives it a public
# https link. The app talks to the DB at localhost:5432, so this MUST run on
# the machine where that DB is reachable (your laptop). Keep this running for
# the link to stay up.
#
# Two modes, auto-detected:
#   * NAMED tunnel  -> stable URL on your own domain. Requires a one-time:
#         cloudflared tunnel login
#         cloudflared tunnel create client-tracker
#         cloudflared tunnel route dns client-tracker tracker.yourdomain.com
#     then set TUNNEL_HOSTNAME below (or via env).
#   * QUICK tunnel  -> zero setup, but the *.trycloudflare.com URL changes
#     every restart. Used automatically if no named tunnel is configured.
#
# Usage:  ./tools/client_tracker/run_tracker.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/../.." && pwd)"
PORT=5055

# Optional: set this (here or as an env var) to use a stable named-tunnel URL.
TUNNEL_HOSTNAME="${TUNNEL_HOSTNAME:-}"
TUNNEL_NAME="${TUNNEL_NAME:-client-tracker}"

cd "$PROJECT_ROOT"

# --- preflight ---------------------------------------------------------------
if ! grep -q '^TRACKER_PASSWORD=' .env 2>/dev/null; then
  echo "ERROR: TRACKER_PASSWORD is not set in .env. Add it before running:" >&2
  echo "       TRACKER_PASSWORD=your-strong-shared-password" >&2
  exit 1
fi

cleanup() {
  echo "Shutting down…"
  [[ -n "${APP_PID:-}" ]] && kill "$APP_PID" 2>/dev/null || true
  [[ -n "${TUN_PID:-}" ]] && kill "$TUN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- start the Flask app -----------------------------------------------------
echo "Starting Client Tracker on http://127.0.0.1:$PORT …"
python tools/client_tracker/tracker_app.py &
APP_PID=$!

# Give the app a moment to bind before the tunnel forwards to it.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  sleep 0.5
done

# --- start the tunnel --------------------------------------------------------
if [[ -n "$TUNNEL_HOSTNAME" ]]; then
  echo "Starting NAMED tunnel '$TUNNEL_NAME' -> https://$TUNNEL_HOSTNAME"
  cloudflared tunnel run --url "http://localhost:$PORT" "$TUNNEL_NAME" &
  TUN_PID=$!
  echo "Public link: https://$TUNNEL_HOSTNAME  (login with the .env password)"
else
  echo "No TUNNEL_HOSTNAME set -> using a QUICK tunnel (URL changes each run)."
  echo "Watch the output below for the https://….trycloudflare.com link:"
  cloudflared tunnel --url "http://localhost:$PORT" &
  TUN_PID=$!
fi

# Keep running until either process exits (then trap cleans up the other).
# Portable poll loop (macOS ships Bash 3.2, which lacks `wait -n`).
while kill -0 "$APP_PID" 2>/dev/null && kill -0 "$TUN_PID" 2>/dev/null; do
  sleep 1
done
