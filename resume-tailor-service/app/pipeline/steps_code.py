"""Code steps of the packet pipeline: plain Python, no LLM.

Each builder returns a `StepSpec(kind="code")` whose result writes only the fields the
step owns. Network calls go through an injectable `ats.Http` so tests never touch a
live site.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md section 4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import job_store
from app.models import JobActivity, JobActivityInput
from app.pipeline.runner import StepContext, StepFailed, StepResult, StepSpec

CLAIM_WINDOW = timedelta(hours=2)
# Statuses that mean the application already went out.
_SUBMITTED_STATUSES = frozenset({"applied", "interview", "offer", "rejected"})


def _session(ctx: StepContext) -> str:
    return f"pipeline {ctx.run.id}"


def _when(activity: JobActivity) -> datetime | None:
    for raw in (activity.occurred_at, activity.created_at):
        try:
            moment = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return None


def _claim(ctx: StepContext) -> StepResult:
    """Claim the dossier for this run, the way interactive agents do (AGENTS.md).

    The claim is an activity, not a field write, so it goes straight through
    `job_store.add_activity` and sits outside the runner's owned field check, which
    covers `StepResult.writes` only."""
    job = ctx.job
    if job.status in _SUBMITTED_STATUSES or any(a.kind == "applied" for a in job.activities):
        return StepResult(output={"claimed": False}, stop="cancelled", reason="already applied")
    session = _session(ctx)
    title = f"Claimed by {session}"
    cutoff = datetime.now(timezone.utc) - CLAIM_WINDOW
    already = False
    for activity in job.activities:
        if not activity.title.startswith("Claimed by"):
            continue
        if activity.title == title or activity.session == session:
            already = True  # this run's own claim, from before a resume
            continue
        moment = _when(activity)
        if moment is None or moment >= cutoff:
            raise StepFailed(f"claimed by another session: {activity.title}"[:200])
    if already:
        return StepResult(output={"claimed": True})
    job_store.add_activity(
        job.id,
        JobActivityInput(
            kind="note", title=title, session=session, external_id=f"pipeline-claim-{ctx.run.id}"
        ),
    )
    return StepResult(output={"claimed": True})


def claim_step() -> StepSpec:
    return StepSpec("claim", "code", run=_claim)
