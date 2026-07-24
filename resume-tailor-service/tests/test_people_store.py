from pathlib import Path
import app.people_store as store
from app.models import PersonInput


def _use_temp(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "people.json")


def test_missing_file_is_empty(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    assert store.load_people() == []


def test_add_assigns_id_and_timestamps(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert p.id and p.created_at and p.updated_at
    assert store.STORE_PATH.is_file()
    people = store.load_people()
    assert len(people) == 1 and people[0].name == "Jane"


def test_update_changes_fields_keeps_created_at(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    updated = store.update_person(p.id, PersonInput(name="Jane Doe", company="Vectra AI", status="sent"))
    assert updated is not None
    assert updated.name == "Jane Doe" and updated.status == "sent"
    assert updated.created_at == p.created_at


def test_update_unknown_returns_none(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    assert store.update_person("nope", PersonInput(name="X", company="Y")) is None


def test_delete_removes_and_reports(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert store.delete_person(p.id) is True
    assert store.load_people() == []
    assert store.delete_person(p.id) is False


def test_get_person(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert store.get_person(p.id).name == "Jane"
    assert store.get_person("missing") is None
