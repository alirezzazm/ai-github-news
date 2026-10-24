#!/usr/bin/env bash
# Pull latest code and redeploy on the server. Run from the repo directory.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose build web
docker compose up -d
docker compose ps
PORT="${WEB_PORT:-$(grep -E '^WEB_PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"
PORT="${PORT:-4200}"
echo "---- waiting for health on :$PORT"
for i in $(seq 1 30); do
  if out=$(curl -fsS "http://127.0.0.1:${PORT}/healthz" 2>/dev/null); then
    echo "healthy: $out"
    exit 0
  fi
  sleep 2
done
echo "web did not become healthy in 60s; check: docker compose logs web" >&2
exit 1
