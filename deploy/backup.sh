#!/usr/bin/env bash
# Backup of the shop: PostgreSQL (custom-format dump) + public media + private media (proof photos).
# Run on the VPS from anywhere; schedule nightly with cron (docs/DEPLOYMENT.md › Backups).
#   BACKUP_DIR (default /var/backups/ashardware), KEEP_DAYS (default 14): older backup files in BACKUP_DIR are removed.
# Restore steps are in docs/DEPLOYMENT.md. Copy backups off the server too (they are useless if the disk dies).
set -euo pipefail
cd "$(dirname "$0")/.."

DEST="${BACKUP_DIR:-/var/backups/ashardware}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE=(docker compose -f docker-compose.prod.yml)
PROJECT=ashardware  # the `name:` in docker-compose.prod.yml (volume names are <project>_<volume>)

umask 077
mkdir -p "$DEST"

"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$DEST/db-$STAMP.dump"
[ -s "$DEST/db-$STAMP.dump" ] || { echo "Database dump is empty: backup FAILED" >&2; exit 1; }

for volume in media private_media; do
  docker run --rm -v "${PROJECT}_${volume}:/data:ro" -v "$DEST:/backup" alpine:3 \
    tar -czf "/backup/${volume}-$STAMP.tar.gz" -C /data .
done

find "$DEST" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'media-*.tar.gz' -o -name 'private_media-*.tar.gz' \) \
  -mtime +"$KEEP_DAYS" -delete
echo "Backup $STAMP written to $DEST"
