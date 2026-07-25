import json
from pathlib import Path
import pytest
from app.bank import load_bank
from app.errors import TailorValidationError
from app.tailor import build_prompt, parse_manifest_json, get_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"

VALID_MANIFEST_DICT = {
    "summary": "Built a 500 widget per hour pipeline, cutting latency 40 percent.",
    "job_selections": [{"job_id": "acme", "bullet_ids": ["acme.bullet.1", "acme.bullet.2"]}],
    "project_selections": [
        {"project_id": "widgetizer", "bullet_ids": ["project.widgetizer.bullet.1"]}
    ],
    "achievement_ids": ["achievement.1"],
    "skill_ids": ["skill.languages"],
    "job_trim_priority": ["acme"],
}

INVALID_MANIFEST_DICT = {**VALID_MANIFEST_DICT, "job_selections": [{"job_id": "ghost", "bullet_ids": []}]}


class _FakeComplete:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        text = self._responses[self.calls]
        self.calls += 1
        return text


def test_build_prompt_includes_jd_and_bank_ids():
    bank = load_bank(FIXTURE)
    prompt = build_prompt("We need a backend engineer.", "Acme", "SWE", bank)
    assert "We need a backend engineer." in prompt
    assert "acme.bullet.1" in prompt
    assert "project.widgetizer.bullet.1" in prompt
    assert "achievement.1" in prompt
    assert "skill.languages" in prompt


def test_parse_manifest_json_handles_plain_json():
    parsed = parse_manifest_json(json.dumps(VALID_MANIFEST_DICT))
    assert parsed["summary"] == VALID_MANIFEST_DICT["summary"]


def test_parse_manifest_json_handles_fenced_json():
    fenced = "```json\n" + json.dumps(VALID_MANIFEST_DICT) + "\n```"
    parsed = parse_manifest_json(fenced)
    assert parsed["job_selections"][0]["job_id"] == "acme"


def test_get_manifest_succeeds_on_first_valid_response():
    bank = load_bank(FIXTURE)
    fake = _FakeComplete([json.dumps(VALID_MANIFEST_DICT)])
    manifest = get_manifest("jd text", "Acme", "SWE", bank, complete=fake)
    assert manifest.job_selections[0].job_id == "acme"
    assert manifest.skill_ids == ["skill.languages"]
    assert fake.calls == 1


def test_get_manifest_retries_once_then_succeeds():
    bank = load_bank(FIXTURE)
    fake = _FakeComplete([json.dumps(INVALID_MANIFEST_DICT), json.dumps(VALID_MANIFEST_DICT)])
    manifest = get_manifest("jd text", "Acme", "SWE", bank, complete=fake, max_retries=1)
    assert manifest.job_selections[0].job_id == "acme"
    assert fake.calls == 2


def test_get_manifest_raises_after_exhausting_retries():
    bank = load_bank(FIXTURE)
    fake = _FakeComplete([json.dumps(INVALID_MANIFEST_DICT), json.dumps(INVALID_MANIFEST_DICT)])
    with pytest.raises(TailorValidationError):
        get_manifest("jd text", "Acme", "SWE", bank, complete=fake, max_retries=1)
    assert fake.calls == 2


def test_get_manifest_retries_on_malformed_json_then_succeeds():
    bank = load_bank(FIXTURE)
    fake = _FakeComplete(["not json at all", json.dumps(VALID_MANIFEST_DICT)])
    manifest = get_manifest("jd text", "Acme", "SWE", bank, complete=fake, max_retries=1)
    assert manifest.job_selections[0].job_id == "acme"
    assert fake.calls == 2


def test_get_manifest_raises_tailor_validation_error_on_persistent_malformed_json():
    bank = load_bank(FIXTURE)
    fake = _FakeComplete(["not json at all", "still not json"])
    with pytest.raises(TailorValidationError):
        get_manifest("jd text", "Acme", "SWE", bank, complete=fake, max_retries=1)
    assert fake.calls == 2
