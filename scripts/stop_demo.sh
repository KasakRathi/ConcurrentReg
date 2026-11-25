#!/usr/bin/env bash
# Stop the demo backend and dashboard. Add --db to stop the MySQL container too (its data is kept).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUIET=0; DB=0
for arg in "$@"; do [ "$arg" = "--quiet" ] && QUIET=1; [ "$arg" = "--db" ] && DB=1; done
say() { [ "$QUIET" = 1 ] || echo "$@"; }
for name in backend frontend; do
  file="$ROOT/.demo-pids/$name.pid"
  if [ -f "$file" ]; then
    pid="$(cat "$file")"
    kill "$pid" 2>/dev/null && say "stopped $name ($pid)"
    # vite starts a child node process: stop whatever still listens on the port
    rm -f "$file"
  fi
done
for port in 8000 5173; do
  pid="$(lsof -tiTCP:$port -sTCP:LISTEN 2>/dev/null | head -1)"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null && say "freed port $port"
done
[ "$DB" = 1 ] && docker stop creg-demo-mysql >/dev/null 2>&1 && say "stopped MySQL"
exit 0
