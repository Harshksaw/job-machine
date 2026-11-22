import pytest

from app import job_store, research_store
from app.sources import jobicy


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(jobicy, "PAUSE_SECONDS", 0)


def _job(n=1, title="Software Engineer", company="Acme", level="Entry"):
    return {
        "id": n,
        "url": f"https://jobicy.com/jobs/{n}",
        "jobTitle": title,
        "companyName": company,
        "jobGeo": "Canada",
        "jobLevel": level,
        "salaryMin": 70000,
        "salaryMax": 90000,
        "salaryCurrency": "CAD",
        "salaryPeriod": "year",
        "pubDate": "2026-11-02T00:00:00",
        "jobDescription": "<p>Build things.</p>",
    }


def test_stages_finds_and_never_creates_dossiers():
    seen = []

    def fetch(url):
        seen.append(url)
        return {"jobs": [_job(), _job(2, company="Beta")]}

    result = jobicy.run_search("canada", fetch=fetch)
    assert job_store.load_jobs() == []
    assert any("geo=canada" in url and "industry=dev" in url for url in seen)
    assert result["fetched"] == 2 and len(result["new"]) == 2
    staged = research_store.list_items("jobicy-canada")
    beta = next(item for item in staged if item["company"] == "Beta")
    assert beta["source"] == "Jobicy"
    assert beta["salary"] == "CAD 70000 to 90000 per year"
    assert beta["jd_text"] == "Build things."
    assert beta["open_to_canada"] is True


def test_senior_titles_are_skipped_and_reruns_do_not_duplicate():
    payload = {"jobs": [_job(), _job(2, title="Senior Backend Engineer", level="Senior")]}
    first = jobicy.run_search("canada", fetch=lambda url: payload)
    assert first["senior_skipped"] == 1 and len(first["new"]) == 1
    again = jobicy.run_search("canada", fetch=lambda url: payload)
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_unknown_preset_fails_clearly():
    with pytest.raises(ValueError):
        jobicy.run_search("nope", fetch=lambda url: {"jobs": []})
