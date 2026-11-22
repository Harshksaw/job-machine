import pytest

from app import job_store, research_store
from app.sources import remote_ok


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")


def _job(n=1, position="Software Engineer", company="Acme", location="Worldwide"):
    return {
        "id": n,
        "url": f"https://remoteok.com/remote-jobs/{n}",
        "position": position,
        "company": company,
        "location": location,
        "salary_min": 100000,
        "salary_max": 140000,
        "date": "2026-11-04T00:00:00",
        "description": "<p>Build things.</p>",
    }


def test_drops_the_terms_row_and_credits_remote_ok():
    result = remote_ok.run_search("software", fetch=lambda: [
        {"legal": "Please credit Remote OK as the source."},
        _job(),
        _job(2, position="Account Executive", company="SalesCo"),
    ])
    assert job_store.load_jobs() == []
    assert result["fetched"] == 2 and result["senior_skipped"] == 1 and len(result["new"]) == 1
    item = research_store.list_items("remote-ok-software")[0]
    assert item["source"] == "Remote OK"
    assert item["company"] == "Acme"
    assert item["salary"] == "USD 100000 to 140000 per year"
    assert item["jd_text"] == "Build things."


def test_country_limited_roles_are_marked_closed_to_canada():
    remote_ok.run_search("software", fetch=lambda: [_job(location="USA")])
    assert research_store.list_items()[0]["open_to_canada"] is False


def test_senior_titles_are_skipped_and_reruns_do_not_duplicate():
    payload = [_job(), _job(2, position="Senior Backend Engineer")]
    first = remote_ok.run_search("software", fetch=lambda: payload)
    assert first["senior_skipped"] == 1 and len(first["new"]) == 1
    again = remote_ok.run_search("software", fetch=lambda: payload)
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_unknown_preset_fails_clearly():
    with pytest.raises(ValueError):
        remote_ok.run_search("nope", fetch=lambda: [])
