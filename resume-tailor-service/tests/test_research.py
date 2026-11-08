import pytest
from fastapi.testclient import TestClient

from app import fantastic, job_store, research_store
from app.main import app

H = {"X-Job-Machine": "dashboard"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(fantastic, "USAGE_PATH", tmp_path / "usage.json")


def _job(n, org="Acme", scope=None):
    return {
        "id": n, "title": "Software Engineer", "organization": org,
        "url": f"https://jobs.lever.co/{org.lower()}/{n:036d}", "source": "lever.co",
        "locations_derived": ["United Kingdom"], "ai_work_arrangement": "Remote Solely",
        "ai_remote_location_derived": scope or ["United Kingdom"],
        "description_text": "Build things.", "date_posted": "2026-11-07T00:00:00",
    }


def test_research_preset_stages_instead_of_creating_dossiers():
    result = fantastic.run_search("uk-remote", 2, fetch=lambda _: [_job(1), _job(2, "Beta", ["Worldwide"])])
    assert job_store.load_jobs() == []
    staged = research_store.list_items("uk-remote")
    assert {i["company"] for i in staged} == {"Acme", "Beta"}
    by_company = {i["company"]: i for i in staged}
    assert by_company["Acme"]["open_to_canada"] is False
    assert by_company["Beta"]["open_to_canada"] is True
    assert len(result["new"]) == 2


def test_research_dedupes_on_url():
    fantastic.run_search("au-remote", 1, fetch=lambda _: [_job(1)])
    again = fantastic.run_search("au-remote", 1, fetch=lambda _: [_job(1)])
    assert again["new"] == [] and len(research_store.list_items()) == 1


def test_agents_can_stage_and_promote_through_the_api():
    client = TestClient(app)
    payload = {"company": "Gamma", "role": "AI Engineer", "url": "https://jobs.ashbyhq.com/gamma/" + "a" * 36,
               "source": "Cursor portal sweep", "remote_scope": "Canada", "open_to_canada": True}
    assert client.post("/api/research", json=payload).status_code == 403
    created = client.post("/api/research", json=payload, headers=H).json()
    item_id = created["item"]["id"]
    assert client.get("/api/research?status=new").json()[0]["company"] == "Gamma"
    promoted = client.post(f"/api/research/{item_id}/promote", headers=H).json()
    dossier = job_store.get_job(promoted["dossier_id"])
    assert dossier.status == "discovered" and dossier.company == "Gamma"
    assert research_store.get(item_id)["status"] == "promoted"


def test_dismiss_marks_item():
    client = TestClient(app)
    item, _ = research_store.add({"company": "Delta", "role": "Dev", "url": "https://x.example/1"})
    assert client.post(f"/api/research/{item['id']}/dismiss", headers=H).json() == {"ok": True}
    assert research_store.get(item["id"])["status"] == "dismissed"
