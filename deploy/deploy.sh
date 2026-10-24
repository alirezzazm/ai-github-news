#!/usr/bin/env bash
# Pull latest code and redeploy on the server. Run from the repo directory.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose build web
docker compose up -d
docker compose ps
echo "---- health"
curl -fsS http://127.0.0.1:${WEB_PORT:-4200}/healthz && echo
