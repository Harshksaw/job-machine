"""Stored results of mail sync runs: Postgres when DATABASE_URL is set, one JSON file
per collection otherwise (tests and CI), like `app/pipeline/store.py`.

- `mail_events`: one document per Gmail message id, holding the classified event (or
  `ignored` when it was not about an application) and what the run did with it:
  `written`, `duplicate`, `held`, `unmatched` or `ignored`. The MCP `search_mail_events`
  tool and the dashboard read these; nobody reads Gmail for them.
- `mail_sync_state`: one document with the newest message date of the last completed
  run, which sets the next run's window.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from app import doc_store
from app.pipeline.models import now_iso

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EVENTS = "mail_events"
STATE = "mail_sync_state"
STATE_ID = "mail_sync"
EVENT_STATUSES = ("written", "duplicate", "held", "unmatched", "ignored")

_LOCK = threading.RLock()
_JSON_BACKENDS: dict[Path, doc_store.JsonFileBackend] = {}
_BACKEND_OVERRIDE = None


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    tmp.replace(path)


def _store(collection: str):
    backend = _BACKEND_OVERRIDE or doc_store.sql_backend_from_env()
    if backend is not None:
        return backend
    path = DATA_DIR / f"{collection}.json"
    with _LOCK:
        if path not in _JSON_BACKENDS:
            _JSON_BACKENDS[path] = doc_store.JsonFileBackend(
                lambda: _read(path), lambda items: _write(path, items), threading.RLock()
            )
        return _JSON_BACKENDS[path]


def known_ids() -> set[str]:
    return {doc["id"] for doc in _store(EVENTS).all(EVENTS)}


def save_events(records: list[dict]) -> None:
    """Upsert by Gmail message id. A record already stored keeps its first `seen_at`."""
    with _store(EVENTS).transaction(EVENTS) as tx:
        for record in records:
            if record.get("status") not in EVENT_STATUSES:
                raise ValueError(f"mail event status must be one of {EVENT_STATUSES}")
            existing = tx.get(record["id"]) or {}
            doc = {**existing, **record, "seen_at": existing.get("seen_at") or now_iso()}
            tx.put(doc, {"status": doc["status"], "match_key": doc.get("dossier_id") or "",
                         "sort_key": doc.get("date", "")})


def list_events(*, company: str = "", outcome: str = "", status: str = "", since: str = "",
                q: str = "", limit: int = 100) -> list[dict]:
    """Newest first. `company` and `q` match case insensitively as substrings."""
    events = _store(EVENTS).all(EVENTS)
    company, q = company.strip().lower(), q.strip().lower()

    def keep(doc: dict) -> bool:
        if company and company not in (doc.get("company") or "").lower():
            return False
        if outcome and doc.get("outcome") != outcome:
            return False
        if status and doc.get("status") != status:
            return False
        if since and (doc.get("date") or "") < since:
            return False
        if q:
            text = " ".join(str(doc.get(key) or "") for key in ("company", "role", "note", "subject", "sender"))
            if q not in text.lower():
                return False
        return True

    kept = sorted((doc for doc in events if keep(doc)), key=lambda d: (d.get("date") or "", d["id"]), reverse=True)
    return kept[:max(0, limit)]


def get_state() -> dict:
    return _store(STATE).get(STATE, STATE_ID) or {"id": STATE_ID}


def save_state(**changes) -> dict:
    with _store(STATE).transaction(STATE) as tx:
        doc = {**(tx.get(STATE_ID) or {"id": STATE_ID}), **changes, "updated_at": now_iso()}
        tx.put(doc, {"sort_key": doc["updated_at"]})
        return doc
