"""The job store and jobs API suites, rerun against the SQL backend (SQLite).

Production runs the same SqlBackend on Neon Postgres; SQLite keeps this suite
offline and secret-free. Tests that assert on the JSON file itself are skipped.
"""
import pytest
from sqlalchemy import select

from app import doc_store, job_store
from app.models import JobCaptureInput, JobWorkspaceInput

from tests import test_job_store as json_suite
from tests import test_jobs_api as api_suite

_FILE_ONLY = {"test_malformed_store_is_never_overwritten"}


@pytest.fixture(autouse=True)
def sql_backend(monkeypatch, tmp_path):
    backend = doc_store.SqlBackend(f"sqlite:///{tmp_path / 'jobs.db'}")
    monkeypatch.setattr(job_store, "_BACKEND_OVERRIDE", backend)
    return backend


def _rerun(module):
    for name in dir(module):
        if name.startswith("test_") and name not in _FILE_ONLY:
            globals()[f"{name}_on_sql"] = getattr(module, name)


_rerun(json_suite)
_rerun(api_suite)


def test_inbox_reads_the_summary_column_not_full_dossiers(sql_backend):
    job = job_store.add_job(
        JobWorkspaceInput(company="Acme", role="SWE", jd_text="x" * 5000)
    )
    with sql_backend.engine.connect() as conn:
        summary = conn.execute(
            select(doc_store.documents.c.summary).where(doc_store.documents.c.id == job.id)
        ).scalar_one()
    assert summary["company"] == "Acme"
    assert "jd_text" not in summary
    assert [s.id for s in job_store.list_summaries()] == [job.id]


def test_dedupe_uses_the_canonical_url_index(sql_backend):
    first, created = job_store.capture_job(
        JobCaptureInput(
            company="Acme",
            role="SWE",
            job_url="https://job-boards.greenhouse.io/acme/jobs/123?trk=x&utm_source=li",
        )
    )
    again, created_again = job_store.capture_job(
        JobCaptureInput(company="Acme Inc", role="Engineer",
                        job_url="https://boards.greenhouse.io/acme/jobs/123")
    )
    assert created and not created_again
    assert again.id == first.id


def test_a_write_touches_only_its_own_row(sql_backend):
    keep = job_store.add_job(JobWorkspaceInput(company="Keep", role="SWE"))
    edit = job_store.add_job(JobWorkspaceInput(company="Edit", role="SWE"))
    before = job_store.get_job(keep.id)
    job_store.update_job(
        edit.id, JobWorkspaceInput(company="Edit", role="SWE", notes="changed")
    )
    assert job_store.get_job(keep.id) == before
    assert job_store.get_job(edit.id).notes == "changed"


@pytest.fixture
def sql_people_and_sessions(monkeypatch, sql_backend):
    from app import people_store, session_store

    monkeypatch.setattr(people_store, "_BACKEND_OVERRIDE", sql_backend)
    monkeypatch.setattr(session_store, "_BACKEND_OVERRIDE", sql_backend)
    return people_store, session_store


def test_people_round_trip_on_sql(sql_people_and_sessions):
    from app.models import PersonInput

    people_store, _ = sql_people_and_sessions
    person = people_store.add_person(PersonInput(name="Ada", company="Acme"))
    assert people_store.person_exists(person.id)
    updated = people_store.update_person(person.id, PersonInput(name="Ada L", company="Acme"))
    assert updated.name == "Ada L"
    assert [p.name for p in people_store.load_people()] == ["Ada L"]
    assert people_store.delete_person(person.id)
    assert people_store.load_people() == []


def test_session_events_are_idempotent_on_sql(sql_people_and_sessions):
    from app.models import SessionEventInput

    _, session_store = sql_people_and_sessions
    first = session_store.append_event(
        SessionEventInput(session="S1", kind="note", title="one", external_id="x1")
    )
    again = session_store.append_event(
        SessionEventInput(session="S1", kind="note", title="dup", external_id="x1")
    )
    other = session_store.append_event(SessionEventInput(session="S1", kind="note", title="two"))
    assert again.id == first.id
    assert [e.title for e in session_store.list_events(session="S1")] == ["one", "two"]
    assert session_store.list_sessions()[0].event_count == 2
    assert other.id != first.id
