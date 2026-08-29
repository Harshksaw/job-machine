"""JSON-file store for outreach people. Local, single-user, no DB — mirrors the
project's 'filesystem is the index' approach. Writes are atomic (temp + replace)
and guarded by a lock (sync endpoints run in a threadpool)."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.errors import PeopleStoreError
from app.models import Person, PersonInput

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "people.json"
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_strict() -> list[dict]:
    try:
        raw = STORE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError) as exc:
        raise PeopleStoreError("could not read the people store") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PeopleStoreError(
            "people store is malformed; refusing to overwrite it"
        ) from exc
    if not isinstance(data, list):
        raise PeopleStoreError(
            "people store must contain a JSON list; refusing to overwrite it"
        )
    return [row for row in data if isinstance(row, dict)]


def _read() -> list[dict]:
    try:
        return _read_strict()
    except PeopleStoreError:
        return []


def _write(items: list[dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_name(STORE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_PATH)


def load_people() -> list[Person]:
    out = []
    for raw in _read():
        try:
            out.append(Person.model_validate(raw))
        except ValueError:
            continue  # skip corrupt rows, never crash the list
    return out


def get_person(person_id: str) -> Person | None:
    for raw in _read():
        if raw.get("id") == person_id:
            return Person.model_validate(raw)
    return None


def add_person(data: PersonInput) -> Person:
    with _LOCK:
        items = _read_strict()
        now = _now()
        person = Person(**data.model_dump(), id=uuid.uuid4().hex,
                        created_at=now, updated_at=now)
        items.append(person.model_dump())
        _write(items)
        return person


def update_person(person_id: str, data: PersonInput) -> Person | None:
    with _LOCK:
        items = _read_strict()
        for i, raw in enumerate(items):
            if raw.get("id") == person_id:
                person = Person(**data.model_dump(), id=person_id,
                                created_at=raw.get("created_at", _now()),
                                updated_at=_now())
                items[i] = person.model_dump()
                _write(items)
                return person
        return None


def person_matches_job(
    person: Person,
    job_id: str,
    company: str,
    role: str = "",
) -> bool:
    if person.job_id:
        return person.job_id == job_id
    if person.company.strip().lower() != company.strip().lower():
        return False
    person_role = (person.role or "").strip().lower()
    return not person_role or person_role == role.strip().lower()


def people_for_job(job_id: str, company: str, role: str = "") -> list[Person]:
    """People pinned to this listing, plus company-level contacts without a job_id."""
    pinned: list[Person] = []
    company_level: list[Person] = []
    for person in load_people():
        if not person_matches_job(person, job_id, company, role):
            continue
        if person.job_id:
            pinned.append(person)
        else:
            company_level.append(person)
    return pinned + company_level


def delete_person(person_id: str) -> bool:
    with _LOCK:
        items = _read_strict()
        kept = [raw for raw in items if raw.get("id") != person_id]
        if len(kept) == len(items):
            return False
        _write(kept)
        return True


def person_exists(person_id: str) -> bool:
    with _LOCK:
        return any(raw.get("id") == person_id for raw in _read_strict())
