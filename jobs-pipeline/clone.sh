#!/usr/bin/env bash
# One-shot RDS -> local jobs-local restore.
# pg_dump emits GIN indexes on gin_trgm_ops; those fail unless pg_trgm exists
# in the target DB *before* restore. This script creates the extension first.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

docker compose up -d
docker compose exec -T jobs-db pg_isready -U postgres -d job_registry >/dev/null
docker compose exec -T jobs-db psql -U postgres -d job_registry -c \
  "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;"

# postgres:17 must match RDS major (currently 17.9) or pg_dump aborts.
echo "dumping RDS into jobs-local (this takes a while)..."
docker run --rm -i postgres:17 pg_dump --no-owner --no-acl "$RDS_DSN" \
  | docker exec -i jobs-local psql -q -U postgres -d job_registry
echo "done."
