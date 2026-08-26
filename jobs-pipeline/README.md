# jobs-pipeline — local mirror of RDS `job_registry`

Full local Postgres mirror of the canonical jobs DB (`job_registry` on the
`tc-jobs-db` RDS instance), refreshed on demand, plus a profile-filter query
that surfaces jobs worth applying to.

Everything runs under your account (Docker + `uv`), so it never depends on the
assistant's blocked outbound DB access.

## 0. Prereqs
- Docker Desktop running
- `uv` (already installed)

## 1. One-time setup
```sh
cd jobs-pipeline
cp .env.example .env        # already filled for this machine if .env exists
docker compose up -d        # starts local Postgres on 127.0.0.1:5433
```

## 2. Initial full clone (the "firehose", run once; large -> background it)
Loads the entire RDS `job_registry` (schema + all rows) into the local
container. Uses `postgres:17` to match RDS 17.9, and creates `pg_trgm` **before**
restore so GIN `gin_trgm_ops` indexes do not abort the load.
```sh
chmod +x clone.sh
nohup ./clone.sh > clone.out 2>clone.err &
tail -f clone.out
```
The previous one-liner (`postgres:16` dump into a DB without `pg_trgm`) is what
produced `clone.err`. Do not use it.

## 3. Inspect the real schema
```sh
uv run --with 'psycopg[binary]' python jobs.py schema
```
Confirms the jobs table name, primary key, watermark column, and all columns.
Use it to tune the filter regexes in `jobs.py` (`INCLUDE` / `EXCLUDE` /
`NOSPONSOR`) if the column names differ from the defaults.

## 4. Incremental refresh (manual — pulls only new rows since last run)
```sh
uv run --with 'psycopg[binary]' python jobs.py sync
```
Watermark-based and idempotent: safe to run anytime; it only fetches rows newer
than the local max, so daily cost is ~the new rows (~10k/day), not the whole DB.

## 5. Get jobs for our needs (profile filter -> relevant_jobs.csv)
```sh
uv run --with 'psycopg[binary]' python jobs.py query
```
Writes `relevant_jobs.csv` (title/company/location/date/url) of matches:
SWE / full-stack / backend / frontend / AI-ML / mobile, early-career (excludes
senior/staff/lead/manager/etc.), drops hard "no sponsorship", last 30 days.
Feed the top rows into the dashboard dossier + apply workflow.

## Notes
- Secrets live only in `.env` (gitignored). Rotate the RDS password if it was
  ever exposed.
- This mirrors on write to the LOCAL db only; RDS is read-only here.
