import pytest

from app.mail import store


@pytest.fixture(autouse=True)
def mail_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def _event(i, **extra):
    return {"id": f"m{i}", "company": "Acme", "role": "Engineer", "date": f"2026-02-0{i}",
            "outcome": "rejected", "confident": True, "note": "", "status": "written", **extra}


def test_save_is_an_upsert_that_keeps_first_seen():
    store.save_events([_event(1)])
    first = store.list_events()[0]["seen_at"]
    store.save_events([_event(1, status="duplicate")])
    events = store.list_events()
    assert len(events) == 1 and events[0]["status"] == "duplicate" and events[0]["seen_at"] == first
    assert store.known_ids() == {"m1"}


def test_status_must_be_known():
    with pytest.raises(ValueError):
        store.save_events([_event(1, status="sent")])


def test_filters_and_newest_first():
    store.save_events([
        _event(1), _event(2, company="Globex", outcome="interview", status="held"),
        _event(3, note="take home test", outcome="assessment"),
    ])
    assert [e["id"] for e in store.list_events()] == ["m3", "m2", "m1"]
    assert [e["id"] for e in store.list_events(company="glob")] == ["m2"]
    assert [e["id"] for e in store.list_events(outcome="assessment")] == ["m3"]
    assert [e["id"] for e in store.list_events(status="held")] == ["m2"]
    assert [e["id"] for e in store.list_events(since="2026-02-02")] == ["m3", "m2"]
    assert [e["id"] for e in store.list_events(q="TAKE HOME")] == ["m3"]
    assert len(store.list_events(limit=1)) == 1


def test_state_round_trip():
    assert store.get_state() == {"id": "mail_sync"}
    store.save_state(newest_date="2026-02-03", last_run_id="r1")
    store.save_state(last_run_id="r2")
    state = store.get_state()
    assert state["newest_date"] == "2026-02-03" and state["last_run_id"] == "r2"
