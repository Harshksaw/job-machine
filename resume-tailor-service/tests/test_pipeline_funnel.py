"""The Flow tab: funnel events (a record of each bucket a dossier or research item is
put in, queryable by date) and GET /api/pipeline/funnel, the Source, Region tier,
Stage, top jobs tree. Temp JSON stores, and SQLite for the event store."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import doc_store, job_store, research_store, search
from app.models import JobWorkspaceInput
from app.pipeline import api, funnel, runner, steps_agent, store
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline

HEADERS = {"X-Job-Machine": "dashboard"}


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(funnel, "HARVEST_DIR", tmp_path / "harvest")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(search.router)
    return TestClient(app)


def _job(**extra):
    extra.setdefault("company", "Acme")
    extra.setdefault("role", "Backend Engineer")
    return job_store.add_job(JobWorkspaceInput(**extra))


# events


@pytest.fixture(params=["json", "sql"])
def backend(request, monkeypatch, tmp_path):
    if request.param == "sql":
        monkeypatch.setattr(store, "_BACKEND_OVERRIDE", doc_store.SqlBackend(f"sqlite:///{tmp_path / 'f.db'}"))
    return request.param


def test_events_are_recorded_and_filtered_by_date(backend):
    funnel.record("eligible", job_id="j1", source="LinkedIn", step="eligibility", run_id="r1",
                  at="2026-11-20T10:00:00+00:00")
    funnel.record("promoted", item_id="i1", source="remotive", at="2026-11-25T10:00:00+00:00")

    every = funnel.list_events()
    assert [e["bucket"] for e in every] == ["eligible", "promoted"]
    assert every[0]["source"] == "linkedin" and every[0]["job_id"] == "j1" and every[0]["run_id"] == "r1"
    assert [e["bucket"] for e in funnel.list_events(since="2026-11-21")] == ["promoted"]
    assert [e["bucket"] for e in funnel.list_events(until="2026-11-21")] == ["eligible"]


def test_a_failing_event_store_never_breaks_the_caller(monkeypatch):
    monkeypatch.setattr(funnel, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    funnel.record_safely("eligible", job_id="j1")  # logs, does not raise


def test_pipeline_steps_record_their_buckets_and_the_terminal_status():
    job = _job(source="Wellfound")
    adapters = {
        "eligibility": FakeAdapter("a", [AdapterResult(outcome="ok", output={"eligible": True, "reason": "Remote CA."})]),
        "fit_score": FakeAdapter("b", [AdapterResult(outcome="ok", output={"score": 4, "reason": "Thin match."})]),
    }
    pipeline = Pipeline("t", (steps_agent.eligibility_step(), steps_agent.fit_score_step(deps=("eligibility",))))
    created = store.create_run(job.id, pipeline.name, pipeline.order)

    runner.run(created.id, pipeline, owner="w1", resolve_chain=lambda step: [adapters[step.name]])

    events = [(e["step"], e["bucket"]) for e in funnel.list_events() if e["job_id"] == job.id]
    assert events == [("eligibility", "eligible"), ("fit_score", "retained"), ("run", "retained_for_review")]
    assert {e["source"] for e in funnel.list_events()} == {"wellfound"}


def test_promote_and_dismiss_record_research_events(client):
    kept, _ = research_store.add({"company": "Beta", "role": "Engineer", "url": "https://x.test/1",
                                  "source": "Himalayas", "preset": "remote-us"})
    gone, _ = research_store.add({"company": "Gamma", "role": "Engineer", "url": "https://x.test/2",
                                  "source": "Remotive", "preset": "remote-eu"})

    assert client.post(f"/api/research/{kept['id']}/promote", headers=HEADERS).status_code == 200
    assert client.post(f"/api/research/{gone['id']}/dismiss", headers=HEADERS).status_code == 200

    events = {(e["item_id"], e["bucket"], e["source"]) for e in funnel.list_events()}
    assert events == {(kept["id"], "promoted", "himalayas"), (gone["id"], "dismissed", "remotive")}


# helpers


@pytest.mark.parametrize("raw, key", [
    ("LinkedIn", "linkedin"), ("wellfound.com", "wellfound"), ("Remote OK", "remote_ok"),
    ("ATS watchlist", "ats_watchlist"), ("Greenhouse board", "ats_watchlist"), ("", "manual"),
    ("Working Nomads", "working_nomads"), ("Some New Board!", "some_new_board"),
])
def test_source_keys(raw, key):
    assert funnel.source_key(raw) == key


def test_tier_reads_an_explicit_field_first_else_a_provisional_guess():
    assert funnel._tier_of({"tier": "a2", "location": "Remote, Canada"}) == ("A2", False)
    assert funnel._tier_of({"location": "Remote, Canada"}) == ("A", True)
    assert funnel._tier_of({"location": "Remote (US only)"}) == ("A2", True)
    assert funnel._tier_of({"location": "Remote, Germany"}) == ("E", True)
    assert funnel._tier_of({"location": ""}) == ("unknown", True)
    assert funnel._tier_of({"notes": "Pipeline r1: eligible (Tier A2), US only"}) == ("A2", True)


def test_tier_uses_the_shared_region_classifier():
    # app.regions.classify_location, the same rules as the harvest and the research staging.
    assert funnel._tier_of({"location": "Remote (New Zealand)"}) == ("A2", True)
    assert funnel._tier_of({"location": "Somewhere"}) == ("A2", True)  # another non India country
    assert funnel._tier_of({"location": "Remote, Switzerland"}) == ("E", True)
    # The description says where the company is based.
    assert funnel._tier_of({"location": "Worldwide", "jd_text": "A Berlin-based startup."}) == ("E", True)
    assert funnel._tier_of({"location": "Worldwide", "description": "Headquartered in Pune, India."}) == (
        "excluded", True)
    assert funnel._tier_of({"location": "Bengaluru, India"}) == ("excluded", True)
    assert funnel._tier_of({"location": "Toronto (hybrid)"}) == ("excluded", True)
    # An explicit tier still wins over the location and the description, and "drop" is excluded.
    assert funnel._tier_of({"tier": "E", "location": "Canada"}) == ("E", False)
    assert funnel._tier_of({"tier": "drop", "location": "Canada"}) == ("excluded", False)
    # The newest exact tier token in the notes, never "Tier A" read out of "Tier A2".
    assert funnel._tier_of({"location": "Canada", "notes": "Tier A (canada)\nPipeline r2: Tier E"}) == ("E", True)


def test_tier_e_is_labelled_europe_last_and_sorts_after_a2(client):
    _job(company="Euro", source="LinkedIn", location="Remote, Germany")
    _job(company="Kiwi", source="LinkedIn", location="New Zealand")
    _job(company="Can", source="LinkedIn", location="Canada")
    body = client.get("/api/pipeline/funnel").json()
    children = _node(body["tree"], "linkedin")["children"]
    assert [c["key"] for c in children] == ["A", "A2", "E"]
    assert _node(children, "E")["label"] == "Tier E, Europe (last)"
    assert body["tiers"]["E"] == 1 and body["tiers"]["excluded"] == 0


# the tree


def _node(nodes, key):
    return next(node for node in nodes if node["key"] == key)


def test_funnel_tree_counts_source_tier_stage_and_lists_top_jobs(client):
    for score, status in ((9, "ready"), (8, "ready"), (4, "discovered")):
        _job(company=f"Co{score}", source="LinkedIn", location="Remote, Canada", fit_score=score, status=status)
    applied = _job(company="Applied Co", source="LinkedIn", location="Remote, Canada", status="applied")
    research_store.add({"company": "Delta", "role": "Engineer", "url": "https://x.test/9",
                        "source": "Remotive", "location": "Remote, Germany", "preset": "remote-eu"})

    body = client.get("/api/pipeline/funnel").json()

    assert body["total"] == 5
    linkedin = _node(body["tree"], "linkedin")
    assert linkedin["count"] == 4 and linkedin["kind"] == "source"
    tier_a = _node(linkedin["children"], "A")
    assert tier_a["count"] == 4 and tier_a["provisional"] is True
    ready = _node(tier_a["children"], "ready")
    assert ready["count"] == 2
    assert [leaf["job"]["company"] for leaf in ready["children"]] == ["Co9", "Co8"]
    assert ready["children"][0]["job"]["fit_score"] == 9 and ready["children"][0]["kind"] == "job"
    assert _node(tier_a["children"], "retained")["count"] == 1
    assert _node(tier_a["children"], "applied")["children"][0]["job"]["id"] == applied.id
    remotive = _node(body["tree"], "remotive")
    assert _node(_node(remotive["children"], "E")["children"], "research_new")["count"] == 1
    assert body["stages"]["ready"] == 2 and body["stages"]["research_new"] == 1
    assert body["harvest"] is None


def test_top_jobs_stop_at_ten(client):
    for index in range(12):
        _job(company=f"Co{index}", source="Wellfound", location="Canada", fit_score=7, status="ready")
    body = client.get("/api/pipeline/funnel").json()
    ready = _node(_node(_node(body["tree"], "wellfound")["children"], "A")["children"], "ready")
    assert ready["count"] == 12 and len(ready["children"]) == 10


def test_run_outcomes_place_a_dossier_in_its_bucket(client):
    job = _job(source="LinkedIn", location="Canada")
    run = store.create_run(job.id, "packet", ["claim"])
    store.finish_run(run.id, "ineligible", "senior only")
    body = client.get("/api/pipeline/funnel").json()
    tier = _node(_node(body["tree"], "linkedin")["children"], "A")
    assert _node(tier["children"], "ineligible")["count"] == 1


def test_the_harvest_summary_adds_fetched_and_dropped_counts(client):
    funnel.HARVEST_DIR.mkdir()
    (funnel.HARVEST_DIR / "remote_candidates.summary.json").write_text(json.dumps({
        "run_at": "2026-11-26T08:00:00+00:00",
        "sources": {"remotive": {"fetched": 120, "kept": {"A": 3, "A2": 5, "E": 2},
                                 "dropped": {"senior title": 70, "india based": 40}}},
    }))
    research_store.add({"company": "Delta", "role": "Engineer", "url": "https://x.test/9",
                        "source": "Remotive", "location": "Remote, Canada", "preset": "remote-ca"})

    body = client.get("/api/pipeline/funnel").json()

    remotive = _node(body["tree"], "remotive")
    assert remotive["fetched"] == 120 and remotive["dropped"] == 110 and remotive["count"] == 1
    dropped = _node(remotive["children"], "dropped")
    assert dropped["kind"] == "dropped" and dropped["count"] == 110
    assert {(r["key"], r["count"]) for r in dropped["children"]} == {("senior title", 70), ("india based", 40)}
    assert _node(remotive["children"], "A2")["kept"] == 5
    assert body["harvest"] == {"run_at": "2026-11-26T08:00:00+00:00", "fetched": 120, "kept": 10, "dropped": 110}


def test_a_broken_harvest_file_is_ignored(client):
    funnel.HARVEST_DIR.mkdir()
    (funnel.HARVEST_DIR / "remote_candidates.summary.json").write_text("{nope")
    assert client.get("/api/pipeline/funnel").status_code == 200


def test_since_keeps_records_created_or_moved_in_the_range(client):
    old = _job(company="Old", source="LinkedIn", location="Canada")
    moved = _job(company="Moved", source="LinkedIn", location="Canada")
    for job in (old, moved):
        store_doc = job_store.get_job(job.id).model_copy(update={"created_at": "2026-10-01T00:00:00+00:00"})
        with job_store._transaction() as tx:
            job_store._put(tx, store_doc)
    funnel.record("eligible", job_id=moved.id, source="LinkedIn", at="2026-11-26T09:00:00+00:00")

    body = client.get("/api/pipeline/funnel", params={"since": "2026-11-20", "until": "2026-11-27"}).json()

    assert body["total"] == 1 and body["events"] == {"eligible": 1}
    assert client.get("/api/pipeline/funnel", params={"since": "soon"}).status_code == 422


def test_only_the_named_harvest_summary_counts_and_only_inside_the_range(client):
    funnel.HARVEST_DIR.mkdir()
    summary = {"run_at": "2026-11-26T08:00:00+00:00",
               "sources": {"remotive": {"fetched": 100, "kept": {"A": 1}, "dropped": {"senior title": 99}}}}
    (funnel.HARVEST_DIR / "remote_candidates.summary.json").write_text(json.dumps(summary))
    (funnel.HARVEST_DIR / "older.summary.json").write_text(json.dumps(summary))

    assert client.get("/api/pipeline/funnel").json()["harvest"]["fetched"] == 100
    inside = client.get("/api/pipeline/funnel", params={"since": "2026-11-25"}).json()
    outside = client.get("/api/pipeline/funnel", params={"since": "2026-11-27"}).json()
    assert inside["harvest"]["fetched"] == 100
    assert outside["harvest"] is None and all(n["key"] != "remotive" for n in outside["tree"])


def test_worldwide_with_an_exclusion_is_not_tier_a():
    assert funnel._tier_of({"location": "Worldwide"}) == ("A", True)
    assert funnel._tier_of({"location": "Global remote, excluding Canada"})[0] != "A"
    assert funnel._tier_of({"location": "Worldwide, US work authorization required"}) == ("A2", True)


def test_failed_and_active_runs_get_their_own_stage(client):
    failed = _job(company="Failed Co", source="LinkedIn", location="Canada", status="ready")
    active = _job(company="Busy Co", source="LinkedIn", location="Canada")
    store.finish_run(store.create_run(failed.id, "packet", ["claim"]).id, "failed", "no adapter")
    store.create_run(active.id, "packet", ["claim"])
    stages = client.get("/api/pipeline/funnel").json()["stages"]
    assert stages["run_failed"] == 1 and stages["in_pipeline"] == 1
