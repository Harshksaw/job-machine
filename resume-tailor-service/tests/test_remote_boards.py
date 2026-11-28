import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1]
SCRIPT = SERVICE / "scripts" / "remote_boards.py"
spec = importlib.util.spec_from_file_location("remote_boards", SCRIPT)
remote_boards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote_boards)

JD = "Build and ship product features. " * 20  # over the 300 character floor


def _row(location, role="Software Engineer", company="Acme", url=None, posted="2026-11-20"):
    return {
        "source": "Test", "company": company, "role": role,
        "job_url": url or f"https://example.com/{company}/{location or 'none'}",
        "location": location, "seniority": "", "salary": "", "posted": posted, "jd_text": JD,
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(url):
        raise AssertionError(f"network call in a test: {url}")
    monkeypatch.setattr(remote_boards, "fetch_json", refuse)
    monkeypatch.setattr(remote_boards.time, "sleep", lambda _: None)


def test_himalayas_and_jobicy_do_not_filter_to_canada_server_side(monkeypatch):
    urls = []

    def fake(url):
        urls.append(url)
        return {"jobs": []}
    monkeypatch.setattr(remote_boards, "fetch_json", fake)
    remote_boards.himalayas()
    remote_boards.jobicy()
    assert any("himalayas.app" in u for u in urls)
    assert any("jobicy.com" in u for u in urls)
    assert not [u for u in urls if "country=" in u.lower() or "geo=" in u.lower()]


def test_himalayas_reads_location_objects_and_strings(monkeypatch):
    jobs = [
        {"guid": "g1", "title": "Software Engineer", "companyName": "A",
         "locationRestrictions": [{"name": "United Kingdom"}, {"name": "Germany"}]},
        {"guid": "g2", "title": "Developer", "companyName": "B", "locationRestrictions": ["Canada"]},
        {"guid": "g3", "title": "Developer", "companyName": "C", "locationRestrictions": []},
    ]
    calls = []

    def fake(url):
        calls.append(url)
        return {"jobs": jobs if len(calls) == 1 else []}
    monkeypatch.setattr(remote_boards, "fetch_json", fake)
    rows = remote_boards.himalayas()
    assert [r["location"] for r in rows] == ["United Kingdom, Germany", "Canada", "Worldwide"]


def test_harvest_tiers_every_row_and_counts_per_source():
    rows = {
        "Board1": [
            _row("Canada", company="Can"),
            _row("USA", company="Usa"),
            _row("Germany", company="Ger"),
            _row("US, India", company="Ind"),
            _row("Worldwide", role="Senior Software Engineer", company="Sen"),
        ],
        "Board2": [
            _row("New Zealand", company="Nzl"),
            _row("Worldwide", company="Wld", posted="2020-01-01"),
        ],
    }
    sources = [(name, (lambda got=got: got)) for name, got in rows.items()]
    kept, summary = remote_boards.harvest(sources, since="2026-11-01", known_jobs=[])

    assert [(r["company"], r["tier"], r["region"]) for r in kept] == [
        ("Can", "A", "canada"), ("Usa", "A2", "us"), ("Nzl", "A2", "new zealand"), ("Ger", "E", "europe"),
    ]
    assert set(summary) == {"run_at", "sources"}
    assert summary["sources"]["Board1"] == {
        "fetched": 5, "kept": {"A": 1, "A2": 1, "E": 1}, "dropped": {"india": 1, "title": 1},
    }
    assert summary["sources"]["Board2"] == {
        "fetched": 2, "kept": {"A": 0, "A2": 1, "E": 0}, "dropped": {"stale": 1},
    }


def test_harvest_records_a_failed_board_and_keeps_going():
    def broken():
        raise RuntimeError("HTTP 500")
    kept, summary = remote_boards.harvest(
        [("Dead", broken), ("Live", lambda: [_row("Canada")])], since="2026-11-01", known_jobs=[])
    assert len(kept) == 1
    assert summary["sources"]["Dead"]["fetched"] == 0
    assert "HTTP 500" in summary["sources"]["Dead"]["error"]


def test_main_writes_output_and_summary_to_data_by_default(tmp_path, monkeypatch, capsys):
    out = tmp_path / "data" / "remote_candidates.json"
    monkeypatch.setattr(remote_boards, "DEFAULT_OUT", out)
    monkeypatch.setattr(remote_boards, "SOURCES", (("Only", lambda: [_row("UK", posted="")]),))
    monkeypatch.setattr(remote_boards, "load_jobs", lambda: [])
    remote_boards.main([])

    rows = json.loads(out.read_text())
    assert [(r["tier"], r["region"]) for r in rows] == [("A2", "uk")]
    summary = json.loads(remote_boards.summary_path(out).read_text())
    assert summary["sources"]["Only"]["kept"] == {"A": 0, "A2": 1, "E": 0}
    assert "Only: fetched 1" in capsys.readouterr().err


def test_default_output_lives_in_the_gitignored_data_folder():
    assert remote_boards.DEFAULT_OUT == SERVICE / "data" / "remote_candidates.json"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.parametrize("path", [
    "resume-tailor-service/data/remote_candidates.json",
    "resume-tailor-service/data/remote_candidates.summary.json",
    "remote_candidates.json",
    "remote_candidates.summary.json",
    "resume-tailor-service/remote_candidates.json",
    "resume-tailor-service/remote_candidates.summary.json",
])
def test_harvest_outputs_are_gitignored(path):
    repo = SERVICE.parent
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=repo)
    assert result.returncode == 0, f"{path} is not gitignored"
