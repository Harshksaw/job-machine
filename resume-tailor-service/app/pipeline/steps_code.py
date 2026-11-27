"""Code steps of the packet pipeline: plain Python, no LLM.

Each builder returns a `StepSpec(kind="code")` whose result writes only the fields the
step owns. Network calls go through an injectable `ats.Http` so tests never touch a
live site.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md section 4.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app import job_store
from app.models import JobActivity, JobActivityInput
from app.pipeline import ats
from app.pipeline.runner import StepContext, StepFailed, StepResult, StepSpec

CLAIM_WINDOW = timedelta(hours=2)
# Below this a JD is too thin to score or tailor against; the agent fallback takes over.
JD_MIN_CHARS = 800
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


def _urls(ctx: StepContext) -> list[str]:
    seen: list[str] = []
    for url in (ctx.job.apply_url, ctx.job.job_url):
        url = (url or "").strip()
        if url and url not in seen:
            seen.append(url)
    return seen


def fetch_jd_step(http: ats.Http | None = None) -> StepSpec:
    def fetch(ctx: StepContext) -> StepResult:
        existing = (ctx.job.jd_text or "").strip()
        if len(existing) >= JD_MIN_CHARS:
            return StepResult(output={"source": "existing"})
        best_kind, best = "", ""
        for url in _urls(ctx):
            kind, text = ats.fetch_description(url, ats.http if http is None else http)
            if len(text) > len(best):
                best_kind, best = kind, text
        writes = {"jd_text": best} if len(best) > len(existing) else {}
        chars = len(best) if writes else len(existing)
        output: dict = {"source": best_kind if writes else "existing", "chars": chars}
        if chars < JD_MIN_CHARS:
            # The agent fallback (M4) picks this up; the step itself does not fail.
            output["needs_agent"] = True
        return StepResult(output=output, writes=writes)

    return StepSpec("fetch_jd", "code", owns=("jd_text",), run=fetch)


Check = Callable[[str], tuple[str, str]]
_LIVENESS_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_liveness.py"
_check: Check | None = None


def _default_check() -> Check:
    """`check(url)` from scripts/check_liveness.py, loaded once by path (scripts/ is not
    a package), so the nightly sweep and this step share one implementation."""
    global _check
    if _check is None:
        spec = importlib.util.spec_from_file_location("check_liveness", _LIVENESS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _check = module.check
    return _check


def liveness_step(check: Check | None = None) -> StepSpec:
    def live(ctx: StepContext) -> StepResult:
        url = (ctx.job.apply_url or ctx.job.job_url or "").strip()
        state, evidence = (check or _default_check())(url)
        output = {"state": state, "evidence": evidence}
        if state != "closed":
            return StepResult(output=output)
        line = f"Pipeline {ctx.run.id}: posting closed ({evidence}) at {url}"
        notes = (ctx.job.notes or "").rstrip("\n")
        return StepResult(
            output=output,
            writes={"notes": f"{notes}\n{line}" if notes else line},
            stop="closed_posting",
            reason=f"posting closed: {evidence}",
        )

    return StepSpec("liveness", "code", owns=("notes",), run=live)


def _follow(url: str, get: ats.Http) -> tuple[str, str]:
    """Final URL after redirects, trying HEAD then GET; ("", why) when neither answers."""
    why = "no answer"
    for method in ("HEAD", "GET"):
        try:
            status, final, _ = get(method, url)
        except Exception as exc:
            why = f"{method} failed: {type(exc).__name__}"
            continue
        if 200 <= status < 400 and final:
            if ats.is_ats_posting(final) or ats.is_careers_page(final):
                return final, ""
            why = f"redirect ended at {final}, not an employer posting"
        else:
            why = f"{method} http {status}"
    return "", why


def resolve_apply_url_step(http: ats.Http | None = None) -> StepSpec:
    def resolve(ctx: StepContext) -> StepResult:
        current = (ctx.job.apply_url or "").strip()
        if current:
            return StepResult(output={"apply_url": current, "source": "existing"})
        job_url = (ctx.job.job_url or "").strip()
        if ats.is_ats_posting(job_url):
            return StepResult(output={"apply_url": job_url, "source": "job_url"},
                              writes={"apply_url": job_url})
        if ats.is_board(job_url):
            final, why = _follow(job_url, ats.http if http is None else http)
            if final:
                return StepResult(output={"apply_url": final, "source": "redirect"},
                                  writes={"apply_url": final})
            reason = f"board listing did not lead to the employer: {why}"
        elif job_url:
            reason = "job_url is not an ATS posting or a known board"
        else:
            reason = "dossier has no job_url"
        # Left empty for the agent fallback (M4); an unconfirmed URL is never written.
        return StepResult(output={"needs_agent": True, "reason": reason[:300]})

    return StepSpec("resolve_apply_url", "code", owns=("apply_url",), run=resolve)
