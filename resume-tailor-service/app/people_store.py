"""JSON-file store for outreach people. Local, single-user, no DB — mirrors the
project's 'filesystem is the index' approach. Writes are atomic (temp + replace)
and guarded by a lock (sync endpoints run in a threadpool)."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import Person, PersonInput

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "people.json"
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> list[dict]:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


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
        items = _read()
        now = _now()
        person = Person(**data.model_dump(), id=uuid.uuid4().hex,
                        created_at=now, updated_at=now)
        items.append(person.model_dump())
        _write(items)
        return person


def update_person(person_id: str, data: PersonInput) -> Person | None:
    with _LOCK:
        items = _read()
        for i, raw in enumerate(items):
            if raw.get("id") == person_id:
                person = Person(**data.model_dump(), id=person_id,
                                created_at=raw.get("created_at", _now()),
                                updated_at=_now())
                items[i] = person.model_dump()
                _write(items)
                return person
        return None


def delete_person(person_id: str) -> bool:
    with _LOCK:
        items = _read()
        kept = [raw for raw in items if raw.get("id") != person_id]
        if len(kept) == len(items):
            return False
        _write(kept)
        return True
