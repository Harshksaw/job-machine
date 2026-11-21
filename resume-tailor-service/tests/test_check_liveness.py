import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_liveness.py"
SPEC = importlib.util.spec_from_file_location("check_liveness", SCRIPT)
assert SPEC and SPEC.loader
liveness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(liveness)


def test_nightly_deletes_only_explicitly_closed(monkeypatch):
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    jobs = [
        {"id": "closed", "job_url": "https://closed.example/job", "status": "ready", "updated_at": old},
        {"id": "unknown", "job_url": "https://unknown.example/job", "status": "ready", "updated_at": old},
        {"id": "applied", "job_url": "https://applied.example/job", "status": "applied", "updated_at": old},
    ]
    deleted = []

    def api_request(url, *, method="GET"):
        if method == "GET":
            return 200, json.dumps(jobs)
        deleted.append(url)
        return 204, ""

    monkeypatch.setattr(liveness, "_api_request", api_request)
    monkeypatch.setattr(
        liveness,
        "check",
        lambda url: ("closed", "gone") if "closed" in url else ("unknown", "unavailable"),
    )

    report = liveness.run_nightly("http://service", older_than_days=30)

    assert report["results"]["closed"]["action"] == "deleted"
    assert report["results"]["unknown"]["action"] == "retained"
    assert "applied" not in report["results"]
    assert deleted == ["http://service/api/jobs/closed"]


def test_nightly_dry_run_does_not_delete(monkeypatch):
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    monkeypatch.setattr(
        liveness, "_api_request", lambda url, *, method="GET": (200, json.dumps([
            {"id": "closed", "job_url": "https://closed.example/job", "status": "ready", "updated_at": old}
        ])) if method == "GET" else (_ for _ in ()).throw(AssertionError("must not delete"))
    )
    monkeypatch.setattr(liveness, "check", lambda url: ("closed", "gone"))

    report = liveness.run_nightly("http://service", older_than_days=30, dry_run=True)

    assert report["results"]["closed"]["action"] == "would_delete"


def test_liveness_check_preserves_unknown_for_network_error(monkeypatch):
    monkeypatch.setattr(liveness, "_get", lambda url: (0, url, "offline"))

    assert liveness.check("https://boards.greenhouse.io/acme/jobs/123") == (
        "unknown", "greenhouse http 0"
    )
