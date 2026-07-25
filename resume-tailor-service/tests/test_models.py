import pytest
from pydantic import ValidationError
from app.models import Manifest, JobSelection, ProjectSelection, TailorRequest, TailorResponse


def _sample_manifest_kwargs():
    return dict(
        summary="Backend engineer with distributed systems experience.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_manifest_parses_valid_data():
    m = Manifest(**_sample_manifest_kwargs())
    assert m.job_selections[0].job_id == "acme"
    assert m.skill_ids == []


def test_manifest_missing_field_raises():
    kwargs = _sample_manifest_kwargs()
    del kwargs["summary"]
    with pytest.raises(ValidationError):
        Manifest(**kwargs)


def test_tailor_request_requires_all_fields():
    req = TailorRequest(jd_text="We need a backend engineer.", company="Acme", role="SWE")
    assert req.company == "Acme"
    with pytest.raises(ValidationError):
        TailorRequest(jd_text="x", company="Acme")


def test_tailor_response_wraps_manifest():
    resp = TailorResponse(pdf_path="/tmp/out.pdf", manifest=Manifest(**_sample_manifest_kwargs()), pages=1)
    assert resp.pages == 1
    assert resp.manifest.achievement_ids == ["achievement.1"]


# Person models tests
from app.models import Person, PersonInput, Link, PERSON_STATUSES


def test_person_input_defaults():
    p = PersonInput(name="Jane Doe", company="Vectra AI")
    assert p.status == "to-reach"
    assert p.role is None
    assert p.links == []
    assert p.title == "" and p.linkedin_url == "" and p.message == ""


def test_person_input_rejects_blank_name():
    with pytest.raises(ValidationError):
        PersonInput(name="   ", company="Vectra AI")


def test_person_input_rejects_blank_company():
    with pytest.raises(ValidationError):
        PersonInput(name="Jane", company="")


def test_person_input_rejects_unknown_status():
    with pytest.raises(ValidationError):
        PersonInput(name="Jane", company="Vectra AI", status="following-up")


def test_person_input_accepts_links_and_known_status():
    p = PersonInput(name="Jane", company="Vectra AI", status="sent",
                    links=[Link(label="GitHub", url="https://github.com/jane")])
    assert p.status == "sent"
    assert p.links[0].label == "GitHub"


def test_person_extends_input_with_server_fields():
    p = Person(name="Jane", company="Vectra AI", id="abc123",
               created_at="2026-07-23T00:00:00+00:00",
               updated_at="2026-07-23T00:00:00+00:00")
    assert p.id == "abc123" and p.name == "Jane"


def test_person_statuses_constant():
    assert PERSON_STATUSES == ("to-reach", "queued", "sent", "replied", "skip")
