import pytest

from app import job_store, research_store
from app.sources import remotive


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(remotive, "PAUSE_SECONDS", 0)


def _job(n=1, title="Software Engineer", company="Acme", location="Worldwide"):
    return {
        "id": n,
        "url": f"https://remotive.com/remote-jobs/software-dev/{n}",
        "title": title,
        "company_name": company,
        "candidate_required_location": location,
        "salary": "USD 80k",
        "publication_date": "2026-11-01T00:00:00",
        "description": "<p>Build things.</p>",
    }


def test_stages_finds_and_never_creates_dossiers():
    result = remotive.run_search("software", fetch=lambda category: {
        "jobs": [_job(), _job(2, company="Beta", location="Canada")],
    })
    assert job_store.load_jobs() == []
    assert result["fetched"] == 2 and len(result["new"]) == 2
    staged = {item["company"]: item for item in research_store.list_items("remotive-software")}
    assert staged["Beta"]["source"] == "Remotive"
    assert staged["Beta"]["url"] == "https://remotive.com/remote-jobs/software-dev/2"
    assert staged["Beta"]["open_to_canada"] is True
    assert staged["Beta"]["jd_text"] == "Build things."
    assert staged["Beta"]["posted"] == "2026-11-01"


def test_country_limited_roles_are_marked_closed_to_canada():
    remotive.run_search("software", fetch=lambda category: {"jobs": [_job(location="USA")]})
    assert research_store.list_items()[0]["open_to_canada"] is False


def test_senior_titles_are_skipped_and_reruns_do_not_duplicate():
    payload = {"jobs": [_job(), _job(2, title="Senior Backend Engineer")]}
    first = remotive.run_search("software", fetch=lambda category: payload)
    assert first["senior_skipped"] == 1 and len(first["new"]) == 1
    again = remotive.run_search("software", fetch=lambda category: payload)
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_unknown_preset_fails_clearly():
    with pytest.raises(ValueError):
        remotive.run_search("nope", fetch=lambda category: {"jobs": []})
