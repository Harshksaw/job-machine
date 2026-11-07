"""Store for outreach people. A local JSON file by default (atomic temp + replace
writes under a lock), or rows in Postgres when DATABASE_URL is set; see
`app.doc_store`."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import doc_store
from app.errors import PeopleStoreError
from app.models import Person, PersonInput

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "people.json"
# Re-entrant: a transaction may nest inside another on the same thread.
_LOCK = threading.RLock()
_COLLECTION = "people"
_BACKEND_OVERRIDE = None


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


_JSON_BACKEND = doc_store.JsonFileBackend(
    lambda: _read_strict(), lambda items: _write(items), _LOCK
)


def _store():
    return _BACKEND_OVERRIDE or doc_store.sql_backend_from_env() or _JSON_BACKEND


def _all_raw() -> list[dict]:
    store = _store()
    # The JSON list read stays lenient: a malformed file lists as empty.
    return _read() if store is _JSON_BACKEND else store.all(_COLLECTION)


def _index(person: Person) -> dict:
    return {"sort_key": person.created_at}


def load_people() -> list[Person]:
    out = []
    for raw in _all_raw():
        try:
            out.append(Person.model_validate(raw))
        except ValueError:
            continue  # skip corrupt rows, never crash the list
    return out


def get_person(person_id: str) -> Person | None:
    for raw in _all_raw():
        if raw.get("id") == person_id:
            return Person.model_validate(raw)
    return None


def add_person(data: PersonInput) -> Person:
    with _store().transaction(_COLLECTION) as tx:
        now = _now()
        person = Person(**data.model_dump(), id=uuid.uuid4().hex,
                        created_at=now, updated_at=now)
        tx.put(person.model_dump(), _index(person))
        return person


def update_person(person_id: str, data: PersonInput) -> Person | None:
    with _store().transaction(_COLLECTION) as tx:
        raw = tx.get(person_id)
        if raw is None:
            return None
        person = Person(**data.model_dump(), id=person_id,
                        created_at=raw.get("created_at", _now()),
                        updated_at=_now())
        tx.put(person.model_dump(), _index(person))
        return person


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
    with _store().transaction(_COLLECTION) as tx:
        return tx.delete(person_id)


def person_exists(person_id: str) -> bool:
    with _store().transaction(_COLLECTION) as tx:
        return tx.get(person_id) is not None
