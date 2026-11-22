import pytest

from app import job_store, research_store
from app.sources import working_nomads


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")


def _job(n=1, title="Software Engineer", company="Acme", category="Development", location="Worldwide"):
    return {
        "url": f"https://www.workingnomads.com/jobs/{n}",
        "title": title,
        "company_name": company,
        "location": location,
        "category_name": category,
        "pub_date": "2026-11-03",
        "description": "<p>Build things.</p>",
    }


def test_stages_development_and_never_creates_dossiers():
    result = working_nomads.run_search("development", fetch=lambda: [
        _job(), _job(2, company="Beta", category="Sales"), _job(3, title="Senior Engineer"),
    ])
    assert job_store.load_jobs() == []
    assert result["fetched"] == 3 and result["off_category"] == 1 and result["senior_skipped"] == 1
    assert len(result["new"]) == 1
    item = research_store.list_items("working-nomads-development")[0]
    assert item["source"] == "Working Nomads"
    assert item["jd_text"] == "Build things."
    assert item["open_to_canada"] is True


def test_country_limited_roles_are_marked_closed_to_canada():
    working_nomads.run_search("development", fetch=lambda: [_job(location="United States")])
    assert research_store.list_items()[0]["open_to_canada"] is False


def test_reruns_do_not_duplicate():
    payload = [_job()]
    working_nomads.run_search("development", fetch=lambda: payload)
    again = working_nomads.run_search("development", fetch=lambda: payload)
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_unknown_preset_fails_clearly():
    with pytest.raises(ValueError):
        working_nomads.run_search("nope", fetch=lambda: [])
