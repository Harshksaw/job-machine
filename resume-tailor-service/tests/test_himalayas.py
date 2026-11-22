import pytest

from app import job_store, research_store
from app.sources import himalayas


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(himalayas, "PAUSE_SECONDS", 0)


def _job(n, title="Software Engineer", company="Acme", places=None):
    return {
        "guid": f"https://himalayas.app/companies/{company.lower()}/jobs/{n}",
        "applicationLink": f"https://himalayas.app/apply/{n}", "title": title,
        "companyName": company, "seniority": ["Entry-level"], "description": "<p>Build things.</p>",
        "locationRestrictions": [{"name": p} for p in (places or [])],
        "minSalary": 60000, "maxSalary": 80000, "currency": "USD", "pubDate": 1795000000,
    }


def _pages(*pages):
    """A fetch that serves each page once, then an empty page."""
    served = iter(pages)
    return lambda params: {"jobs": next(served, [])}


def test_stages_finds_and_never_creates_dossiers():
    result = himalayas.run_search("canada-entry", fetch=_pages([_job(1), _job(2, company="Beta", places=["Canada"])]))
    assert job_store.load_jobs() == []
    assert result["fetched"] == 2 and len(result["new"]) == 2
    staged = {i["company"]: i for i in research_store.list_items("himalayas-canada-entry")}
    assert staged["Acme"]["open_to_canada"] is True  # no restriction means worldwide
    assert staged["Beta"]["source"] == "Himalayas"
    assert staged["Beta"]["url"] == "https://himalayas.app/apply/2"
    assert staged["Beta"]["salary"] == "60000-80000 USD annual"
    assert staged["Beta"]["jd_text"] == "Build things."


def test_country_limited_roles_are_marked_closed_to_canada():
    himalayas.run_search("uk-au-entry", fetch=_pages([_job(1, places=["United Kingdom"])]))
    assert research_store.list_items()[0]["open_to_canada"] is False


def test_plain_string_locations_and_long_guids_are_handled():
    job = _job(1, places=None) | {"locationRestrictions": ["Canada"], "guid": "https://himalayas.app/x/" + "a" * 120}
    himalayas.run_search("canada-entry", fetch=_pages([job]))
    item = research_store.list_items()[0]
    assert item["open_to_canada"] is True and len(item["id"]) <= 64


def test_senior_titles_are_skipped_and_reruns_do_not_duplicate():
    jobs = [_job(1), _job(2, title="Senior Backend Engineer")]
    first = himalayas.run_search("us-entry", fetch=_pages(jobs))
    assert first["senior_skipped"] == 1 and len(first["new"]) == 1
    again = himalayas.run_search("us-entry", fetch=_pages(jobs))
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_missing_key_and_unknown_preset_fail_clearly(monkeypatch):
    monkeypatch.delenv("HIMALAYAS_API_KEY", raising=False)
    with pytest.raises(himalayas.HimalayasError):
        himalayas.run_search("us-entry")
    with pytest.raises(ValueError):
        himalayas.run_search("nope")
