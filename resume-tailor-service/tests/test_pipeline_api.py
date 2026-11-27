import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline import api, config, store
from app.pipeline.models import AdapterResult
from app.pipeline.router import Health

HEADERS = {"X-Job-Machine": "dashboard"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(api, "HEALTH", Health(blocked_families=lambda: {"codex"}))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_get_config_seeds_defaults(client):
    body = client.get("/api/pipeline/config").json()
    assert body["version"] == 1
    assert "gemini_lite" in body["adapters"]


def test_mutating_routes_need_the_dashboard_header(client):
    body = client.get("/api/pipeline/config").json()
    assert client.put("/api/pipeline/config", json=body).status_code == 403
    assert client.post("/api/pipeline/config/rollback/1").status_code == 403
    assert client.post("/api/pipeline/config/reset").status_code == 403
    assert client.post("/api/pipeline/adapters/codex/test").status_code == 403


def test_put_saves_a_new_version_and_rollback_restores(client):
    body = client.get("/api/pipeline/config").json()
    body["workers"] = 7
    body["adapters"]["cursor"]["enabled"] = False

    saved = client.put("/api/pipeline/config", json=body, headers=HEADERS)
    assert saved.status_code == 200
    assert saved.json()["version"] == 2
    assert client.get("/api/pipeline/config").json()["workers"] == 7

    versions = client.get("/api/pipeline/config/versions").json()
    assert [v["version"] for v in versions] == [2, 1]

    rolled = client.post("/api/pipeline/config/rollback/1", headers=HEADERS).json()
    assert rolled["version"] == 3
    assert rolled["adapters"]["cursor"]["enabled"] is True
    assert client.post("/api/pipeline/config/rollback/99", headers=HEADERS).status_code == 404

    reset = client.post("/api/pipeline/config/reset", headers=HEADERS).json()
    assert reset["version"] == 4


@pytest.mark.parametrize("change", [
    lambda b: b["adapters"]["codex"].update(capabilities=["telepathy"]),
    lambda b: b["adapters"]["codex"].update(command=["codex", "exec"]),
    lambda b: b.update(steps={"fit_score": {"prefer": ["ghost"]}}),
    # gemini_lite is cheap only; fit_score needs reason.
    lambda b: b.update(steps={"fit_score": {"prefer": ["gemini_lite"]}}),
    lambda b: b.update(steps={"no_such_step": {"prefer": ["codex"]}}),
])
def test_bad_configs_are_422_and_not_saved(client, change):
    body = client.get("/api/pipeline/config").json()
    change(body)

    response = client.put("/api/pipeline/config", json=body, headers=HEADERS)

    assert response.status_code == 422
    assert client.get("/api/pipeline/config").json()["version"] == 1


def test_adapters_list_shows_key_set_and_health_never_the_key(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-very-secret")

    rows = {row["name"]: row for row in client.get("/api/pipeline/adapters").json()}

    assert rows["gemini_lite"]["key_set"] is True
    assert rows["codex"]["health"]["healthy"] is False
    assert rows["cursor"]["health"]["healthy"] is True
    assert "AIza-very-secret" not in client.get("/api/pipeline/adapters").text


class Stub:
    def __init__(self, spec):
        self.name = spec.name

    def call(self, prompt, *, run_id, step, schema, timeout):
        assert run_id == "adapter-test"
        return AdapterResult(outcome="unavailable", error="Out of credits", model="m")


def test_adapter_test_records_an_attempt_and_cools_down(client, monkeypatch):
    monkeypatch.setattr(api, "build_adapter", Stub)

    response = client.post("/api/pipeline/adapters/cursor/test", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["outcome"] == "unavailable"
    [attempt] = store.list_attempts("adapter-test")
    assert (attempt.adapter, attempt.outcome, attempt.model) == ("cursor", "unavailable", "m")
    assert api.HEALTH.status(config.load_config().adapters["cursor"])["healthy"] is False
    assert client.post("/api/pipeline/adapters/ghost/test", headers=HEADERS).status_code == 404
