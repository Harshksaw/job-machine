"""Every dashboard source tiers its finds with app.regions: India is dropped, Europe is
kept as Tier E, and each staged item carries tier and region."""
import pytest

from app import job_store, research_store
from app.sources import himalayas, jobicy, remote_ok, remotive, working_nomads


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    for module in (himalayas, jobicy, remotive):
        monkeypatch.setattr(module, "PAUSE_SECONDS", 0)


def _himalayas(jobs):
    pages = iter([jobs])
    return himalayas.run_search("canada-entry", fetch=lambda params: {"jobs": next(pages, [])})


def _himalayas_job(n, company, location):
    return {"guid": f"https://himalayas.app/companies/x/jobs/{n}", "title": "Software Engineer",
            "companyName": company, "seniority": ["Entry-level"], "description": "<p>Build.</p>",
            "locationRestrictions": [{"name": location}], "pubDate": 1795000000}


def _jobicy_job(n, company, location):
    return {"id": n, "url": f"https://jobicy.com/jobs/{n}", "jobTitle": "Software Engineer",
            "companyName": company, "jobGeo": location, "jobLevel": "Entry",
            "pubDate": "2026-11-02T00:00:00", "jobDescription": "<p>Build.</p>"}


def _remotive_job(n, company, location):
    return {"id": n, "url": f"https://remotive.com/remote-jobs/x/{n}", "title": "Software Engineer",
            "company_name": company, "candidate_required_location": location,
            "publication_date": "2026-11-01T00:00:00", "description": "<p>Build.</p>"}


def _nomads_job(n, company, location):
    return {"url": f"https://www.workingnomads.com/jobs/{n}", "title": "Software Engineer",
            "company_name": company, "category_name": "Development", "location": location,
            "pub_date": "2026-11-01T00:00:00", "description": "<p>Build.</p>"}


def _remote_ok_job(n, company, location):
    return {"id": n, "url": f"https://remoteok.com/remote-jobs/{n}", "position": "Software Engineer",
            "company": company, "location": location, "date": "2026-11-01T00:00:00",
            "description": "<p>Build.</p>"}


SOURCES = {
    "himalayas": (_himalayas_job, _himalayas),
    "jobicy": (_jobicy_job, lambda jobs: jobicy.run_search("remote", fetch=lambda url: {"jobs": jobs})),
    "remotive": (_remotive_job, lambda jobs: remotive.run_search("software", fetch=lambda c: {"jobs": jobs})),
    "working_nomads": (_nomads_job, lambda jobs: working_nomads.run_search("development", fetch=lambda: jobs)),
    "remote_ok": (_remote_ok_job, lambda jobs: remote_ok.run_search("software", fetch=lambda: jobs)),
}


@pytest.mark.parametrize("name", list(SOURCES))
def test_source_tiers_finds_drops_india_and_keeps_europe(name):
    make, run = SOURCES[name]
    jobs = [make(1, "Can", "Canada"), make(2, "Usa", "USA"), make(3, "Ger", "Germany"),
            make(4, "Ind", "India"), make(5, "Mix", "US, India")]
    result = run(jobs)

    staged = {i["company"]: i for i in research_store.list_items()}
    assert set(staged) == {"Can", "Usa", "Ger"}
    assert [(staged[c]["tier"], staged[c]["region"]) for c in ("Can", "Usa", "Ger")] == [
        ("A", "canada"), ("A2", "us"), ("E", "europe")]
    assert [staged[c]["open_to_canada"] for c in ("Can", "Usa", "Ger")] == [True, False, False]
    assert result["dropped"] == {"india": 2}
    assert {n["company"]: n["tier"] for n in result["new"]} == {"Can": "A", "Usa": "A2", "Ger": "E"}


def test_jobicy_does_not_ask_the_api_for_canada_only():
    seen = []
    jobicy.run_search("remote", fetch=lambda url: seen.append(url) or {"jobs": []})
    assert seen and not [u for u in seen if "geo=" in u]


def test_himalayas_has_a_preset_with_no_country_filter():
    seen = []
    himalayas.run_search("all-entry", fetch=lambda params: seen.append(params) or {"jobs": []})
    assert seen and all("country" not in p and "worldwide" not in p for p in seen)
