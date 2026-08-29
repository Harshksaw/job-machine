import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import job_store, session_store, sessions


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
    app = FastAPI()
    app.include_router(sessions.router)
    return TestClient(app)


def test_append_and_list_session_events(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/sessions/event",
        json={
            "session": "Wellfound 2026-08-27",
            "kind": "browser",
            "title": "Opened SWARA apply modal",
            "detail": "Guest signup form; not submitted",
            "job_id": "bfd5d99f1d124b9f84f82546af551514",
            "external_id": "swara:apply-open",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["session"] == "Wellfound 2026-08-27"
    assert body["title"].startswith("Opened SWARA")

    duplicate = client.post(
        "/api/sessions/event",
        json={
            "session": "Wellfound 2026-08-27",
            "kind": "browser",
            "title": "Opened SWARA apply modal",
            "detail": "retry",
            "external_id": "swara:apply-open",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == body["id"]

    listed = client.get(
        "/api/sessions/events",
        params={"session": "Wellfound 2026-08-27"},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    summaries = client.get("/api/sessions")
    assert summaries.status_code == 200
    assert summaries.json()[0]["session"] == "Wellfound 2026-08-27"
    assert summaries.json()[0]["event_count"] == 1


def test_session_event_normalizes_ids_before_validation_and_deduplication(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    first = client.post(
        "/api/sessions/event",
        json={
            "session": "Inbox 2026-08-27",
            "kind": "decision",
            "title": "Approved Acme",
            "job_id": " abc123 ",
            "external_id": " approve-acme ",
        },
    )

    assert first.status_code == 201
    assert first.json()["job_id"] == "abc123"
    assert first.json()["external_id"] == "approve-acme"

    duplicate = client.post(
        "/api/sessions/event",
        json={
            "session": "Inbox 2026-08-27",
            "kind": "decision",
            "title": "Retry should deduplicate",
            "job_id": "abc123",
            "external_id": "approve-acme",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]


def test_session_event_reads_skip_malformed_lines_and_keep_latest_limit(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    for title in ("First valid event", "Second valid event"):
        response = client.post(
            "/api/sessions/event",
            json={
                "session": "Inbox 2026-08-27",
                "kind": "note",
                "title": title,
            },
        )
        assert response.status_code == 201

    lines = session_store.STORE_PATH.read_text(encoding="utf-8").splitlines()
    session_store.STORE_PATH.write_text(
        f"{lines[0]}\nnot valid json\n{lines[1]}\n",
        encoding="utf-8",
    )

    all_events = client.get(
        "/api/sessions/events",
        params={"session": "Inbox 2026-08-27", "limit": 100},
    )
    latest = client.get(
        "/api/sessions/events",
        params={"session": "Inbox 2026-08-27", "limit": 1},
    )

    assert [event["title"] for event in all_events.json()] == [
        "First valid event",
        "Second valid event",
    ]
    assert [event["title"] for event in latest.json()] == ["Second valid event"]


@pytest.mark.parametrize("reader_name", ["list_events", "list_sessions"])
def test_session_reads_share_the_append_lock(
    monkeypatch,
    tmp_path,
    reader_name,
):
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
    started = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []

    def read() -> None:
        started.set()
        try:
            getattr(session_store, reader_name)()
        except BaseException as exc:  # pragma: no cover - reported below
            failures.append(exc)
        finally:
            finished.set()

    with session_store._LOCK:
        thread = threading.Thread(target=read)
        thread.start()
        assert started.wait(1)
        assert not finished.wait(0.1)

    assert finished.wait(1)
    thread.join(timeout=1)
    assert not failures
