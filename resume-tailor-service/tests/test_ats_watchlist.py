import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ats_watchlist.py"
spec = importlib.util.spec_from_file_location("ats_watchlist", SCRIPT)
ats_watchlist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ats_watchlist)


def test_load_watchlist_ignores_disabled_boards(tmp_path):
    watchlist = tmp_path / "companies.yaml"
    watchlist.write_text(
        "boards:\n"
        "  - company: Acme\n    provider: greenhouse\n    token: acme\n"
        "  - company: Off\n    provider: lever\n    token: off\n    enabled: false\n"
    )
    assert ats_watchlist.load_watchlist(watchlist) == [
        {"company": "Acme", "provider": "greenhouse", "token": "acme"}
    ]


def test_poll_stages_only_new_roles_and_preserves_full_jd():
    boards = [
        {"company": "Acme", "provider": "greenhouse", "token": "acme"},
        {"company": "Beta", "provider": "lever", "token": "beta"},
        {"company": "Gamma", "provider": "ashby", "token": "gamma"},
    ]
    payloads = []

    def get_json(url):
        if "greenhouse" in url:
            return {"jobs": [{"title": "Software Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {"name": "Toronto"}, "content": "<p>Existing role</p>"}]}
        if "lever" in url:
            return [{"text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/beta/11111111-1111-1111-1111-111111111111", "categories": {"location": "Canada"}, "descriptionPlain": "Build APIs."}]
        return {"jobs": [{"id": "22222222-2222-2222-2222-222222222222", "title": "AI Engineer", "location": "Remote Canada", "descriptionPlain": "Build reliable systems."}]}

    def request_json(url, method, payload):
        if method == "GET":
            return [{"company": "Acme", "role": "Software Engineer", "job_url": "https://job-boards.greenhouse.io/acme/jobs/1?utm_source=x"}]
        payloads.append(payload)
        return {"created": True, "item": payload}

    result = ats_watchlist.poll(boards, get_json=get_json, request_json=request_json)
    assert result == {"fetched": 3, "new": 2, "duplicates": 1, "staged": 2, "failures": []}
    assert {item["source"] for item in payloads} == {"Lever", "Ashby"}
    assert all(item["preset"] == "ats-watchlist" for item in payloads)
    assert any(item["jd_text"] == "Build reliable systems." for item in payloads)


def test_poll_dry_run_never_posts():
    boards = [{"company": "Acme", "provider": "lever", "token": "acme"}]

    def get_json(_):
        return [{"text": "Developer", "hostedUrl": "https://jobs.lever.co/acme/33333333-3333-3333-3333-333333333333", "descriptionPlain": "A role."}]

    def request_json(url, method, payload):
        assert method == "GET"
        return []

    assert ats_watchlist.poll(boards, dry_run=True, get_json=get_json, request_json=request_json)["staged"] == 0


def test_empty_watchlist_does_not_contact_the_service():
    def never_called(*_):
        raise AssertionError("an empty watchlist should not make HTTP requests")

    assert ats_watchlist.poll([], get_json=never_called, request_json=never_called) == {
        "fetched": 0, "new": 0, "duplicates": 0, "staged": 0, "failures": []
    }
