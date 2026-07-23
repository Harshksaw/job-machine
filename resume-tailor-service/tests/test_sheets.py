import httpx
import pytest

from app import sheets
from app.errors import SheetsError


# A host + secret we assert never appear in any raised error message.
_URL = "https://script.google.com/macros/s/SECRET_DEPLOY_ID/exec"
_SECRET = "super-secret-read-token"


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("APPS_SCRIPT_URL", _URL)
    monkeypatch.setenv("APPS_SCRIPT_READ_SECRET", _SECRET)


def _no_leak(msg: str) -> None:
    assert _SECRET not in msg
    assert "SECRET_DEPLOY_ID" not in msg
    assert _URL not in msg


def test_fetch_applications_normalizes_rows(_env, monkeypatch):
    captured = {}

    def fake_get(self, url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "rows": [
                    {
                        "company": "Flowline",
                        "role": "Backend Engineer",
                        "source": "wellfound",
                        "jobUrl": "https://jobs.example/1",
                        "status": "applied",
                        "fit": "8",
                        "people": "2",
                        "hooks": "h",
                        "outreach": "o",
                        "notes": "n",
                        "timestamp": "2026-07-22T10:00:00Z",
                    },
                    {"company": "Blank", "role": "", "jobUrl": None},
                ],
            },
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    apps = sheets.fetch_applications()

    assert len(apps) == 2
    first = apps[0]
    assert first.company == "Flowline"
    assert first.role == "Backend Engineer"
    assert first.job_url == "https://jobs.example/1"  # jobUrl -> job_url
    assert first.fit == "8"
    assert first.timestamp == "2026-07-22T10:00:00Z"
    assert first.tailored_resume_id is None

    # missing / None cells normalize to ""
    assert apps[1].role == ""
    assert apps[1].job_url == ""

    # request carried the read action + secret in params (not in the path)
    assert captured["params"]["action"] == "read"
    assert captured["params"]["secret"] == _SECRET


def test_fetch_applications_network_error_raises_clean(_env, monkeypatch):
    def boom(self, url, **kwargs):
        raise httpx.ConnectError(f"failed connecting to {_URL}")

    monkeypatch.setattr(httpx.Client, "get", boom)
    with pytest.raises(SheetsError) as ei:
        sheets.fetch_applications()
    _no_leak(str(ei.value))


def test_fetch_applications_non_200_raises_clean(_env, monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(500, text="internal error")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(SheetsError) as ei:
        sheets.fetch_applications()
    _no_leak(str(ei.value))


def test_fetch_applications_ok_false_raises_clean(_env, monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"ok": False, "error": "denied"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(SheetsError) as ei:
        sheets.fetch_applications()
    _no_leak(str(ei.value))


def test_fetch_applications_malformed_json_raises_clean(_env, monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=b"<html>not json</html>")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(SheetsError) as ei:
        sheets.fetch_applications()
    _no_leak(str(ei.value))


def test_fetch_applications_missing_env_raises_clean(monkeypatch):
    monkeypatch.delenv("APPS_SCRIPT_URL", raising=False)
    # secret is set but URL is not — the message must not leak the secret
    monkeypatch.setenv("APPS_SCRIPT_READ_SECRET", _SECRET)
    with pytest.raises(SheetsError) as ei:
        sheets.fetch_applications()
    msg = str(ei.value)
    assert msg  # a clear, non-empty message
    _no_leak(msg)
