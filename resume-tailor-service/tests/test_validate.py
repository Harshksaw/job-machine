from pathlib import Path
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.validate import validate_manifest, extract_facts

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"


def _valid_manifest():
    return Manifest(
        summary="Engineer who cut latency 40 percent on a 500 widget/hour pipeline.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1", "acme.bullet.2"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_valid_manifest_has_no_errors():
    bank = load_bank(FIXTURE)
    assert validate_manifest(_valid_manifest(), bank) == []


def test_unknown_job_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].job_id = "does-not-exist"
    errors = validate_manifest(m, bank)
    assert any("does-not-exist" in e for e in errors)


def test_unknown_bullet_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].bullet_ids.append("acme.bullet.99")
    errors = validate_manifest(m, bank)
    assert any("acme.bullet.99" in e for e in errors)


def test_bullet_id_from_wrong_job_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].bullet_ids = ["project.widgetizer.bullet.1"]
    errors = validate_manifest(m, bank)
    assert len(errors) >= 1


def test_unknown_project_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.project_selections[0].project_id = "ghost-project"
    errors = validate_manifest(m, bank)
    assert any("ghost-project" in e for e in errors)


def test_unknown_achievement_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.achievement_ids = ["achievement.does-not-exist"]
    errors = validate_manifest(m, bank)
    assert any("achievement.does-not-exist" in e for e in errors)


def test_job_trim_priority_must_match_job_ids_exactly():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_trim_priority = ["acme", "phantom-job"]
    errors = validate_manifest(m, bank)
    assert any("job_trim_priority" in e for e in errors)


def test_summary_with_untraceable_number_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.summary = "Cut costs by 999 percent using a proprietary framework."
    errors = validate_manifest(m, bank)
    assert any("999" in e for e in errors)


def test_summary_with_traceable_facts_passes():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.summary = "Built a 500 widget per hour pipeline, cutting latency 40 percent."
    assert validate_manifest(m, bank) == []


def test_extract_facts_finds_numbers_and_acronyms():
    facts = extract_facts("Cut costs by 40% using AWS and 12K+ users on a RAG pipeline.")
    assert "40%" in facts
    assert "12K+" in facts
    assert "AWS" in facts
    assert "RAG" in facts
