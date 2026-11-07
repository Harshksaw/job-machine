"""Copy the local JSON stores into the database named by DATABASE_URL(_UNPOOLED).

    uv run python scripts/migrate_to_db.py [--dry-run]

Reads data/jobs.json, data/people.json and data/sessions.jsonl directly (never
through the stores, which would already point at the database), writes every
document with the same index columns the stores compute, then compares counts.
Idempotent: rerunning upserts the same ids. The JSON files are left in place as
the backup; nothing local is deleted.
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app import doc_store, job_store, people_store, session_store  # noqa: E402
from app.models import JobWorkspace, Person, SessionEvent  # noqa: E402


def _jobs() -> list[JobWorkspace]:
    rows = json.loads(job_store.STORE_PATH.read_text(encoding="utf-8"))
    return [JobWorkspace.model_validate(row) for row in rows]


def _people() -> list[Person]:
    if not people_store.STORE_PATH.is_file():
        return []
    rows = json.loads(people_store.STORE_PATH.read_text(encoding="utf-8"))
    return [Person.model_validate(row) for row in rows]


def _events() -> list[SessionEvent]:
    if not session_store.STORE_PATH.is_file():
        return []
    events = []
    for line in session_store.STORE_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            event = session_store._parse_line(line)
            if event is not None:
                events.append(event)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="read and count only")
    args = parser.parse_args()

    jobs, people, events = _jobs(), _people(), _events()
    print(f"local: {len(jobs)} jobs, {len(people)} people, {len(events)} session events")
    if args.dry_run:
        return

    backend = doc_store.sql_backend_from_env()
    if backend is None:
        sys.exit("no DATABASE_URL or DATABASE_URL_UNPOOLED in the environment or .env")

    with backend.transaction("jobs") as tx:
        for job in jobs:
            job_store._put(tx, job)
    with backend.transaction("people") as tx:
        for person in people:
            tx.put(person.model_dump(), people_store._index(person))
    with backend.transaction("session_events") as tx:
        for event in events:
            tx.put(
                event.model_dump(mode="json"),
                {
                    "sort_key": event.created_at,
                    "match_key": (
                        session_store._match_key(event.session, event.external_id)
                        if event.external_id
                        else None
                    ),
                },
            )

    remote = {name: len(backend.all(name)) for name in ("jobs", "people", "session_events")}
    print(f"database: {remote['jobs']} jobs, {remote['people']} people, "
          f"{remote['session_events']} session events")
    expected = {"jobs": len(jobs), "people": len(people), "session_events": len(events)}
    if remote != expected:
        sys.exit(f"COUNT MISMATCH: expected {expected}, got {remote}")
    print("counts match")


if __name__ == "__main__":
    main()
