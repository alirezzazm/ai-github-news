#!/bin/sh
# Nightly compressed pg_dump; keeps the newest $BACKUP_KEEP files.
# Runs inside the postgres:16-alpine image (BusyBox sh/date, pg_dump, gzip).
set -eu
HOUR="${BACKUP_HOUR:-3}"
MINUTE="${BACKUP_MINUTE:-30}"
KEEP="${BACKUP_KEEP:-7}"
DIR="/backups"
mkdir -p "$DIR"

run_backup() {
  stamp="$(date +%Y%m%d-%H%M)"
  out="$DIR/aignews-$stamp.dump.gz"
  echo "[backup] $(date '+%Y-%m-%d %H:%M:%S') starting -> $out"
  if pg_dump -Fc --no-owner --no-privileges | gzip -6 > "$out.tmp"; then
    mv "$out.tmp" "$out"
    echo "[backup] done: $(du -h "$out" | cut -f1)"
  else
    rm -f "$out.tmp"
    echo "[backup] FAILED" >&2
  fi
  # prune: keep the newest $KEEP
  ls -1t "$DIR"/aignews-*.dump.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r f; do
    echo "[backup] pruning $f"; rm -f "$f"
  done
}

# seconds until the next HH:MM (portable: no GNU `date -d` needed)
seconds_until_next() {
  now_h=$(date +%H); now_m=$(date +%M); now_s=$(date +%S)
  now_sec=$(( ${now_h#0} * 3600 + ${now_m#0} * 60 + ${now_s#0} ))
  target_sec=$(( HOUR * 3600 + MINUTE * 60 ))
  diff=$(( target_sec - now_sec ))
  [ "$diff" -le 0 ] && diff=$(( diff + 86400 ))
  echo "$diff"
}

# Wait for the database, then take an immediate backup if none exists yet
for i in $(seq 1 30); do pg_isready -q && break; sleep 5; done
if [ -z "$(ls -1 "$DIR"/aignews-*.dump.gz 2>/dev/null)" ]; then
  run_backup || true
fi

while true; do
  wait_for=$(seconds_until_next)
  echo "[backup] next run in ${wait_for}s (at $HOUR:$MINUTE, TZ=${TZ:-UTC})"
  sleep "$wait_for"
  run_backup || true
  sleep 61
done
