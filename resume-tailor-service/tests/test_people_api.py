import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.people_store as store
from app import people


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "people.json")
    api = FastAPI()
    api.include_router(people.router)
    return TestClient(api)


def _mk(client, **over):
    body = {"name": "Jane Doe", "company": "Vectra AI"}
    body.update(over)
    return client.post("/api/people", json=body)


def test_create_returns_201_with_id(client):
    resp = _mk(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] and body["status"] == "to-reach"


def test_list_and_company_filter(client):
    _mk(client, company="Vectra AI")
    _mk(client, name="Bob", company="Acme Cloud")
    assert len(client.get("/api/people").json()) == 2
    only = client.get("/api/people", params={"company": "vectra ai"}).json()
    assert len(only) == 1 and only[0]["company"] == "Vectra AI"


def test_create_422_on_blank_name(client):
    assert _mk(client, name="").status_code == 422


def test_create_422_on_bad_status(client):
    assert _mk(client, status="following-up").status_code == 422


def test_update(client):
    pid = _mk(client).json()["id"]
    resp = client.put(f"/api/people/{pid}", json={"name": "Jane D", "company": "Vectra AI", "status": "sent"})
    assert resp.status_code == 200 and resp.json()["status"] == "sent"


def test_update_unknown_404(client):
    resp = client.put("/api/people/deadbeef", json={"name": "X", "company": "Y"})
    assert resp.status_code == 404


def test_update_bad_id_400(client):
    resp = client.put("/api/people/..%2fetc", json={"name": "X", "company": "Y"})
    assert resp.status_code in (400, 404)  # rejected, never applied


def test_delete(client):
    pid = _mk(client).json()["id"]
    assert client.delete(f"/api/people/{pid}").status_code == 204
    assert client.delete(f"/api/people/{pid}").status_code == 404
