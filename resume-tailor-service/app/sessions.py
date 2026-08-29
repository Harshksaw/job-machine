"""Session-level narrative log API (append-only JSONL)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from app import session_store
from app.models import SessionEvent, SessionEventInput, SessionSummary

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

router = APIRouter()


def _validate_id(value: str, label: str) -> None:
    if ".." in value or not _ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"invalid {label} id")


@router.get("/api/sessions", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return session_store.list_sessions()


@router.get("/api/sessions/events", response_model=list[SessionEvent])
def list_session_events(
    session: str | None = None,
    job_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SessionEvent]:
    if job_id:
        _validate_id(job_id, "job")
    return session_store.list_events(session=session, job_id=job_id, limit=limit)


@router.post("/api/sessions/event", response_model=SessionEvent, status_code=201)
def append_session_event(data: SessionEventInput) -> SessionEvent:
    if data.job_id:
        _validate_id(data.job_id, "job")
    return session_store.append_event(data)
