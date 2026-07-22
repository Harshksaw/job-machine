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
