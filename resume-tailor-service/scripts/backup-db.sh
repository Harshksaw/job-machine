#!/usr/bin/env bash
# Nightly dump of the local jobmachine database (launchd: com.jobmachine.dbbackup).
# Keeps 14 days in ~/job-machine-backups, outside the repo because dossiers are private.
set -euo pipefail

DEST="${JOB_MACHINE_BACKUP_DIR:-$HOME/job-machine-backups}"
DB="${JOB_MACHINE_DB:-jobmachine}"
mkdir -p "$DEST"
/opt/homebrew/opt/postgresql@16/bin/pg_dump -Fc --no-owner --no-acl -d "$DB" \
  -f "$DEST/$DB-$(date +%Y%m%d-%H%M%S).dump"
find "$DEST" -name "$DB-*.dump" -mtime +14 -delete
echo "backup ok: $(ls -1 "$DEST" | tail -1)"
