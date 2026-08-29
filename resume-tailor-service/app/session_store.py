"""Append-only session narrative log (JSONL). Complements per-job dossier activities."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import SessionEvent, SessionEventInput, SessionSummary

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "sessions.jsonl"
_LOCK = threading.RLock()
_MAX_READ_BYTES = 8 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_line(line: str) -> SessionEvent | None:
    try:
        return SessionEvent.model_validate(json.loads(line))
    except (ValueError, json.JSONDecodeError):
        return None


def _read_all() -> list[SessionEvent]:
    try:
        raw = STORE_PATH.read_bytes()
    except FileNotFoundError:
        return []
    except OSError:
        return []
    if len(raw) > _MAX_READ_BYTES:
        raw = raw[-_MAX_READ_BYTES:]
        if b"\n" in raw:
            raw = raw.split(b"\n", 1)[1]
    events: list[SessionEvent] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        event = _parse_line(line)
        if event is not None:
            events.append(event)
    return events


def append_event(data: SessionEventInput) -> SessionEvent:
    with _LOCK:
        if data.external_id:
            for event in _read_all():
                if (
                    event.session == data.session
                    and event.external_id == data.external_id
                ):
                    return event

        now = _now()
        event = SessionEvent(
            **data.model_dump(),
            id=uuid.uuid4().hex,
            created_at=data.occurred_at or now,
        )
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STORE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event.model_dump(mode="json"), ensure_ascii=True) + "\n"
            )
        return event


def list_events(
    *,
    session: str | None = None,
    job_id: str | None = None,
    limit: int = 100,
) -> list[SessionEvent]:
    with _LOCK:
        events = _read_all()
    if session:
        events = [event for event in events if event.session == session]
    if job_id:
        events = [event for event in events if event.job_id == job_id]
    if limit > 0:
        events = events[-limit:]
    return events


def list_sessions() -> list[SessionSummary]:
    summaries: dict[str, SessionSummary] = {}
    with _LOCK:
        events = _read_all()
    for event in events:
        current = summaries.get(event.session)
        if current is None:
            summaries[event.session] = SessionSummary(
                session=event.session,
                event_count=1,
                last_event_at=event.created_at,
                last_title=event.title,
            )
            continue
        current.event_count += 1
        if event.created_at >= current.last_event_at:
            current.last_event_at = event.created_at
            current.last_title = event.title
    return sorted(
        summaries.values(),
        key=lambda row: row.last_event_at,
        reverse=True,
    )
