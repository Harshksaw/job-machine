from pathlib import Path
import pytest
from app.bank import (
    load_bank, all_job_ids, all_project_ids, all_achievement_ids,
    all_job_bullet_ids, all_project_bullet_ids, bank_text_blob,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"


def test_load_bank_parses_all_sections():
    bank = load_bank(FIXTURE)
    assert bank.contact.name == "Test Person"
    assert bank.education.school == "Test University"
    assert len(bank.jobs) == 1
    assert bank.jobs[0].id == "acme"
    assert len(bank.jobs[0].bullets) == 2
    assert len(bank.projects) == 1
    assert len(bank.achievements) == 1
    assert len(bank.skills) == 1
    assert bank.skills[0].id == "skill.languages"
    assert bank.profile_facts == []


def test_all_job_ids():
    bank = load_bank(FIXTURE)
    assert all_job_ids(bank) == {"acme"}


def test_all_project_ids():
    bank = load_bank(FIXTURE)
    assert all_project_ids(bank) == {"widgetizer"}


def test_all_achievement_ids():
    bank = load_bank(FIXTURE)
    assert all_achievement_ids(bank) == {"achievement.1"}


def test_all_job_bullet_ids_keyed_by_job():
    bank = load_bank(FIXTURE)
    assert all_job_bullet_ids(bank) == {"acme": {"acme.bullet.1", "acme.bullet.2"}}


def test_all_project_bullet_ids_keyed_by_project():
    bank = load_bank(FIXTURE)
    assert all_project_bullet_ids(bank) == {
        "widgetizer": {"project.widgetizer.bullet.1"}
    }


def test_bank_text_blob_contains_all_bullet_text():
    bank = load_bank(FIXTURE)
    blob = bank_text_blob(bank)
    assert "500 widgets per hour" in blob
    assert "40 percent" in blob
    assert "400ms" in blob
    assert "regional Test Hackathon" in blob
    assert "Python, Go" in blob


def test_load_bank_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_bank(Path("/nonexistent/bank.yaml"))
