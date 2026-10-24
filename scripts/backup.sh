#!/bin/sh
# Nightly compressed pg_dump; keeps the newest $BACKUP_KEEP files.
# Runs inside the postgres image (has pg_dump, gzip, find).
set -eu
HOUR="${BACKUP_HOUR:-3}"
MINUTE="${BACKUP_MINUTE:-30}"
KEEP="${BACKUP_KEEP:-7}"
DIR="/backups"
mkdir -p "$DIR"

run_backup() {
  stamp="$(date +%Y%m%d-%H%M)"
  out="$DIR/aignews-$stamp.dump.gz"
  echo "[backup] $(date -Iseconds) starting -> $out"
  if pg_dump -Fc --no-owner --no-privileges | gzip -6 > "$out.tmp"; then
    mv "$out.tmp" "$out"
    echo "[backup] done: $(du -h "$out" | cut -f1)"
  else
    rm -f "$out.tmp"
    echo "[backup] FAILED" >&2
  fi
  # prune: keep newest $KEEP
  ls -1t "$DIR"/aignews-*.dump.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r f; do
    echo "[backup] pruning $f"; rm -f "$f"
  done
}

# Immediate backup on first start if none exists yet (useful right after deploy)
if [ -z "$(ls -1 "$DIR"/aignews-*.dump.gz 2>/dev/null)" ]; then
  sleep 20
  run_backup || true
fi

while true; do
  now=$(date +%s)
  target=$(date -d "today $HOUR:$MINUTE" +%s 2>/dev/null || echo 0)
  if [ "$target" -le "$now" ]; then
    target=$(date -d "tomorrow $HOUR:$MINUTE" +%s)
  fi
  sleep $((target - now))
  run_backup || true
  sleep 60
done
