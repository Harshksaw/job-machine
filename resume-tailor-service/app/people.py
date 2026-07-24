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
def list_people(company: str | None = None) -> list[Person]:
    people = people_store.load_people()
    if company:
        key = company.strip().lower()
        people = [p for p in people if p.company.strip().lower() == key]
    return people


@router.post("/api/people", response_model=Person, status_code=201)
def create_person(data: PersonInput) -> Person:
    return people_store.add_person(data)


@router.put("/api/people/{person_id}", response_model=Person)
def replace_person(person_id: str, data: PersonInput) -> Person:
    _validate_id(person_id)
    updated = people_store.update_person(person_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="person not found")
    return updated


@router.delete("/api/people/{person_id}", status_code=204)
def remove_person(person_id: str) -> None:
    _validate_id(person_id)
    if not people_store.delete_person(person_id):
        raise HTTPException(status_code=404, detail="person not found")
