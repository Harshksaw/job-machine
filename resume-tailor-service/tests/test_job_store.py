from pathlib import Path

import pytest

from app import job_store
from app.errors import JobStoreError
from app.models import (
    Application,
    FitAnalysis,
    GeneratedApplicationKit,
    JobActivityInput,
    JobCaptureInput,
    JobWorkspaceInput,
)


def _use_temp_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")


def test_create_update_and_restore_revision(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    created = job_store.add_job(
        JobWorkspaceInput(company="Acme", role="Backend Engineer", notes="first")
    )
    assert created.activities[0].kind == "created"
    assert created.revisions[0].reason == "Initial dossier"

    updated = job_store.update_job(
        created.id,
        JobWorkspaceInput(
            company="Acme",
            role="Backend Engineer",
            notes="second",
            status="researching",
        ),
        session="LinkedIn 2026-07-23",
    )
    assert updated is not None
    assert updated.notes == "second"
    assert updated.status == "researching"
    assert updated.activities[-1].session == "LinkedIn 2026-07-23"
    assert set(updated.revisions[-1].changed_fields) == {"notes", "status"}

    restored = job_store.restore_revision(updated.id, created.revisions[0].id)
    assert restored is not None
    assert restored.notes == "first"
    assert restored.status == "discovered"
    assert restored.activities[-1].kind == "restored"


def test_activity_external_id_is_deduplicated(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="SWE"))
    event = JobActivityInput(
        title="Imported",
        external_id="sheet:abc",
    )
    once = job_store.add_activity(job.id, event)
    twice = job_store.add_activity(job.id, event)
    assert once is not None and twice is not None
    assert len(twice.activities) == len(once.activities)


def test_generated_kit_and_resume_are_recorded(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="SWE"))
    kit = GeneratedApplicationKit(
        analysis=FitAnalysis(
            score=8,
            recommendation="apply",
            verdict="Strong fit.",
        ),
        cover_letter="Letter",
    )
    generated = job_store.apply_generated_kit(job.id, kit)
    assert generated is not None
    assert generated.fit_score == 8
    assert generated.status == "ready"
    assert generated.cover_letter == "Letter"

    attached = job_store.attach_resume(job.id, "acme-swe-123")
    assert attached is not None
    assert attached.tailored_resume_id == "acme-swe-123"
    assert attached.activities[-1].kind == "resume"


def test_low_fit_kit_stays_active_for_review(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    job = job_store.add_job(
        JobWorkspaceInput(
            company="Acme",
            role="SWE",
            status="researching",
        )
    )
    kit = GeneratedApplicationKit(
        analysis=FitAnalysis(
            score=4,
            recommendation="review",
            verdict="Material gaps need review.",
        ),
        cover_letter="Editable grounded draft.",
    )

    generated = job_store.apply_generated_kit(job.id, kit)

    assert generated is not None
    assert generated.fit_score == 4
    assert generated.status == "researching"
    assert generated.fit_analysis is not None
    assert generated.fit_analysis.recommendation == "review"
    assert generated.cover_letter == "Editable grounded draft."


def test_sheet_upsert_merges_rows_and_deduplicates_events(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    row = Application(
        company="Acme",
        role="SWE",
        source="LinkedIn",
        job_url="https://example.com/job",
        status="applied",
        fit="8",
        notes="Submitted",
        timestamp="2026-07-23T12:00:00Z",
    )
    first, created = job_store.upsert_application(row)
    second, created_again = job_store.upsert_application(row)
    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert second.status == "applied"
    assert second.fit_score == 8
    sheet_events = [event for event in second.activities if event.kind == "sheet"]
    assert len(sheet_events) == 1


def test_list_summaries_omits_large_revision_snapshots(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    job_store.add_job(
        JobWorkspaceInput(
            company="Acme",
            role="SWE",
            jd_text="x" * 500,
        )
    )
    summaries = job_store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].company == "Acme"
    assert summaries[0].revision_count == 1
    assert not hasattr(summaries[0], "jd_text")


def test_capture_upserts_full_listing_context(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    first, created = job_store.capture_job(
        JobCaptureInput(
            company="Acme",
            role="SWE",
            job_url="https://example.com/job",
            source="Wellfound",
            fit_score=8,
            jd_text="Full description",
            session="Wellfound 2026-07-23",
        )
    )
    second, created_again = job_store.capture_job(
        JobCaptureInput(
            company="Acme",
            role="SWE",
            job_url="https://example.com/job",
            status="applied",
            next_action="Find the hiring manager",
            session="Wellfound 2026-07-23",
        )
    )
    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert second.jd_text == "Full description"
    assert second.status == "applied"
    assert second.next_action == "Find the hiring manager"


def test_malformed_store_is_never_overwritten(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    job_store.STORE_PATH.write_text("{broken", encoding="utf-8")
    with pytest.raises(JobStoreError, match="refusing to overwrite"):
        job_store.add_job(JobWorkspaceInput(company="Acme", role="SWE"))
    assert job_store.STORE_PATH.read_text(encoding="utf-8") == "{broken"
