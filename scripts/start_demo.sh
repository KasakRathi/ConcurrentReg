#!/usr/bin/env bash
# One command for the judges' demo: MySQL (Docker), the backend with demo controls on, and the dashboard.
#   ./scripts/start_demo.sh          start everything and open the browser
#   IASL=1 ./scripts/start_demo.sh   same, with IASL (adaptive admission control) switched on; adds the IASL page
#   ./scripts/stop_demo.sh           stop the backend and dashboard   (add --db to stop MySQL too)
set -euo pipefail
# IASL=1 switches the optional adaptive admission control on for the backend. Unset or anything else = off (unchanged behaviour).
IASL_ON=0; [ "${IASL:-0}" = "1" ] && IASL_ON=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PIDS="$ROOT/.demo-pids"; LOGS="$ROOT/.demo-logs"
mkdir -p "$PIDS" "$LOGS"

[ -x .venv/bin/python ] || { echo "Missing .venv. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
[ -d frontend/node_modules ] || (echo "Installing dashboard packages..." && cd frontend && npm install --no-audit --no-fund)

"$ROOT/scripts/demo_db.sh"
set -a; source "$ROOT/.demo.env"; set +a

"$ROOT/scripts/stop_demo.sh" --quiet || true
echo "Resetting the demo data..."
.venv/bin/python -m app.seed

# The three OS-layer settings are the generator's documented defaults; the dashboard can change them live.
if [ "$IASL_ON" = 1 ]; then echo "IASL: ON (IASL_ENABLED=1 for the backend)"; else echo "IASL: off (start with IASL=1 to switch it on)"; fi
IASL_ENABLED="$IASL_ON" QUEUE_CAPACITY="${QUEUE_CAPACITY:-16}" WORKER_COUNT="${WORKER_COUNT:-4}" DB_SEMAPHORE_PERMITS="${DB_SEMAPHORE_PERMITS:-2}" \
  nohup .venv/bin/uvicorn app.main:app --port 8000 > "$LOGS/backend.log" 2>&1 &
echo $! > "$PIDS/backend.pid"
(cd frontend && nohup npx vite --port 5173 --strictPort > "$LOGS/frontend.log" 2>&1 & echo $! > "$PIDS/frontend.pid")

for _ in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8000/demo/info >/dev/null 2>&1 && curl -fs http://localhost:5173/ >/dev/null 2>&1; then
    echo
    echo "Ready."
    echo "  Dashboard : http://localhost:5173/dashboard/demo"
    echo "  Landing   : http://localhost:5173/"
    echo "  Backend   : http://127.0.0.1:8000/docs"
    [ "$IASL_ON" = 1 ] && echo "  IASL page : http://localhost:5173/dashboard/iasl"
    echo "  Logs      : $LOGS"
    command -v open >/dev/null && open "http://localhost:5173/dashboard/demo" || true
    exit 0
  fi
  sleep 1
done
echo "The servers did not become ready. See $LOGS" >&2
exit 1
