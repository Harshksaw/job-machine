"""Research stage: candidate listings that are not dossiers yet.

Searches (Fantastic Jobs research presets, Cursor or OpenCode portal sweeps) land here
first, so the apply queue only ever holds roles someone chose to promote. Same backend
as the dossiers (Neon when DATABASE_URL is set, a local JSON file otherwise), separate
collection.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import doc_store

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "research.json"
_COLLECTION = "research"
_LOCK = threading.RLock()
STATUSES = ("new", "promoted", "dismissed")


def _read() -> list[dict]:
    if not STORE_PATH.exists():
        return []
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def _write(items: list[dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    tmp.replace(STORE_PATH)


_JSON_BACKEND = doc_store.JsonFileBackend(_read, _write, _LOCK)
_BACKEND_OVERRIDE = None


def _store():
    return _BACKEND_OVERRIDE or doc_store.sql_backend_from_env() or _JSON_BACKEND


def add(item: dict) -> tuple[dict, bool]:
    """Insert unless the same url (or id) is already staged. Returns (item, created)."""
    url = (item.get("url") or "").strip()
    with _store().transaction(_COLLECTION) as tx:
        for existing in tx.all():
            if (url and existing.get("url") == url) or existing.get("id") == item.get("id"):
                return existing, False
        doc = {
            "status": "new",
            "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **item,
            "id": str(item.get("id") or uuid.uuid4().hex),
        }
        tx.put(doc, {"status": doc["status"], "sort_key": doc["found_at"], "canonical_url": url or None})
        return doc, True


def list_items(preset: str | None = None, status: str | None = None) -> list[dict]:
    items = _store().all(_COLLECTION)
    if preset:
        items = [i for i in items if i.get("preset") == preset]
    if status:
        items = [i for i in items if i.get("status") == status]
    return sorted(items, key=lambda i: i.get("found_at", ""), reverse=True)


def get(item_id: str) -> dict | None:
    return _store().get(_COLLECTION, item_id)


def set_status(item_id: str, status: str, **extra) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with _store().transaction(_COLLECTION) as tx:
        doc = tx.get(item_id)
        if doc is None:
            return None
        doc = {**doc, **extra, "status": status}
        tx.put(doc, {"status": status, "sort_key": doc.get("found_at"), "canonical_url": doc.get("url") or None})
        return doc
