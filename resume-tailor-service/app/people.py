"""Read/write API for outreach people. No auth (local-only service)."""
import re

from fastapi import APIRouter, HTTPException

from app import people_store
from app.models import Person, PersonInput

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

router = APIRouter()


def _validate_id(person_id: str) -> None:
    if ".." in person_id or not _ID_RE.match(person_id):
        raise HTTPException(status_code=400, detail="invalid person id")


@router.get("/api/people", response_model=list[Person])
def list_people(company: str | None = None, job_id: str | None = None) -> list[Person]:
    people = people_store.load_people()
    if job_id:
        return [p for p in people if p.job_id == job_id]
    if company:
        key = company.strip().lower()
        people = [p for p in people if p.company.strip().lower() == key]
    return people


_DASHES = ("\u2014", "\u2013")


def _reject_dashes(data: PersonInput) -> None:
    # Checked here, not on the model: old sent rows contain dashes and must still load.
    if any(d in data.message for d in _DASHES):
        raise HTTPException(
            status_code=422,
            detail="Outreach message contains an em-dash or en-dash. Use a comma, period, or colon.",
        )


@router.post("/api/people", response_model=Person, status_code=201)
def create_person(data: PersonInput) -> Person:
    _reject_dashes(data)
    return people_store.add_person(data)


_CONTACTED = {"sent", "replied"}
_PRE_SEND = {"queued", "to-reach", "approved"}


@router.put("/api/people/{person_id}", response_model=Person)
def replace_person(person_id: str, data: PersonInput) -> Person:
    _validate_id(person_id)
    current = people_store.get_person(person_id)
    if current is None or data.message != current.message or data.status in _PRE_SEND:
        _reject_dashes(data)
    # A stale client (an old People list) must not un-send someone: a revert
    # back to approved is how a re-send happens.
    if current and current.status in _CONTACTED and data.status in _PRE_SEND:
        raise HTTPException(
            status_code=409,
            detail=f"{current.name} is already {current.status}; refusing to move back "
            f"to {data.status}. Reload and retry.",
        )
    updated = people_store.update_person(person_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="person not found")
    return updated


@router.delete("/api/people/{person_id}", status_code=204)
def remove_person(person_id: str) -> None:
    _validate_id(person_id)
    if not people_store.delete_person(person_id):
        raise HTTPException(status_code=404, detail="person not found")
