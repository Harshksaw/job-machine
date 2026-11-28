"""Code steps of the packet pipeline: plain Python, no LLM.

Each builder returns a `StepSpec(kind="code")` whose result writes only the fields the
step owns. Network calls go through an injectable `ats.Http` so tests never touch a
live site.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md section 4.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app import job_store
from app.models import JobActivity, JobActivityInput, JobWorkspace
from app.pipeline import ats, store
from app.pipeline.models import TERMINAL_STATUSES
from app.pipeline.runner import Pipeline, StepContext, StepFailed, StepResult, StepSpec

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


_APPLIED = "already applied"
_OWN = "own claim"


_PIPELINE_SESSION = re.compile(r"^pipeline (\S+)$")


def _released(activity: JobActivity) -> bool:
    """A claim by a pipeline run that has ended is released: that run no longer works
    the dossier, so it must not block the next run. A claim whose run is unknown (or
    belongs to another tool) stays live until the claim window lapses."""
    match = _PIPELINE_SESSION.match(activity.session or "") or _PIPELINE_SESSION.match(
        activity.title.removeprefix("Claimed by ").strip())
    if match is None:
        return False
    try:
        run = store.get_run(match.group(1))
    except Exception:
        return False
    return run is not None and run.status in TERMINAL_STATUSES


def _claim_conflict(job: JobWorkspace, session: str) -> str:
    """"" when the run may claim the dossier, else why not."""
    if job.status in _SUBMITTED_STATUSES or any(a.kind == "applied" for a in job.activities):
        return _APPLIED
    cutoff = datetime.now(timezone.utc) - CLAIM_WINDOW
    own = False
    for activity in job.activities:
        if not activity.title.startswith("Claimed by"):
            continue
        if activity.title == f"Claimed by {session}" or activity.session == session:
            own = True  # this run's own claim, from before a resume
            continue
        if _released(activity):
            continue
        moment = _when(activity)
        if moment is None or moment >= cutoff:
            return f"claimed by another session: {activity.title}"[:200]
    return _OWN if own else ""


def _claim(ctx: StepContext) -> StepResult:
    """Claim the dossier for this run, the way interactive agents do (AGENTS.md).

    The check runs on the dossier as it is inside the write transaction, not on the step
    snapshot, so two runs cannot both claim it. The claim is an activity, not a field
    write, so it goes through `job_store.add_activity_unless` and sits outside the
    runner's owned field check, which covers `StepResult.writes` only."""
    session = _session(ctx)
    job, conflict = job_store.add_activity_unless(
        ctx.job.id,
        JobActivityInput(kind="note", title=f"Claimed by {session}", session=session,
                         external_id=f"pipeline-claim-{ctx.run.id}"),
        lambda current: _claim_conflict(current, session),
    )
    if job is None:
        raise StepFailed(f"dossier {ctx.job.id} no longer exists")
    if conflict == _APPLIED:
        return StepResult(output={"claimed": False}, stop="cancelled", reason=_APPLIED)
    if conflict and conflict != _OWN:
        raise StepFailed(conflict)
    return StepResult(output={"claimed": True})


def claim_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("claim", "code", deps=deps, run=_claim)


def _urls(ctx: StepContext) -> list[str]:
    seen: list[str] = []
    for url in (ctx.job.apply_url, ctx.job.job_url):
        url = (url or "").strip()
        if url and url not in seen:
            seen.append(url)
    return seen


def fetch_jd_step(http: ats.Http | None = None, deps: tuple[str, ...] = ()) -> StepSpec:
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

    return StepSpec("fetch_jd", "code", deps=deps, owns=("jd_text",), run=fetch)


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


def liveness_step(check: Check | None = None, deps: tuple[str, ...] = ()) -> StepSpec:
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

    return StepSpec("liveness", "code", deps=deps, owns=("notes",), run=live)


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


def resolve_apply_url_step(http: ats.Http | None = None, deps: tuple[str, ...] = ()) -> StepSpec:
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

    return StepSpec("resolve_apply_url", "code", deps=deps, owns=("apply_url",), run=resolve)


MISSING = "not available yet"
# A brief may move a dossier to "ready" only from these; anything later is Harsh's call.
_BRIEF_FROM = frozenset({"discovered", "researching"})


def _clean(text: object) -> str:
    """One line of brief text: no em dashes (AGENTS.md working style), no newlines."""
    value = re.sub(r"\s*\u2014\s*", ", ", str(text or ""))
    return " ".join(value.split())


def _section(title: str, lines: list[str], empty: str = MISSING) -> str:
    return "\n".join([title, *(lines or [empty])])


def _summary(ctx: StepContext) -> list[str]:
    job = ctx.job
    lines = [_clean(f"{job.role} at {job.company}")]
    where = ", ".join(_clean(v) for v in (job.location, job.work_mode) if (v or "").strip())
    if where:
        lines.append(f"Where: {where}")
    if (job.compensation or "").strip():
        lines.append(f"Pay: {_clean(job.compensation)}")
    score = job.fit_analysis.score if job.fit_analysis else job.fit_score
    if score is not None:
        verdict = _clean(job.fit_analysis.verdict) if job.fit_analysis else ""
        lines.append(f"Fit: {score}/10" + (f", {verdict}" if verdict else ""))
    else:
        lines.append(f"Fit: {MISSING}")
    live = ctx.outputs.get("liveness") or {}
    if live.get("state"):
        lines.append(_clean(f"Posting check: {live['state']} ({live.get('evidence', '')})"))
    jd = ctx.outputs.get("fetch_jd") or {}
    if jd.get("needs_agent"):
        lines.append(f"Job description: short or missing, full text {MISSING}")
    return lines


def _apply_at(ctx: StepContext) -> list[str]:
    job = ctx.job
    apply_url, job_url = (job.apply_url or "").strip(), (job.job_url or "").strip()
    reason = _clean((ctx.outputs.get("resolve_apply_url") or {}).get("reason", ""))
    if not (apply_url or job_url or reason):
        return []
    lines = [_clean(apply_url) if apply_url else MISSING + (f" ({reason})" if reason else "")]
    if job_url and job_url != apply_url:
        lines.append(f"Listing: {_clean(job_url)}")
    return lines


def _gaps(ctx: StepContext) -> list[str]:
    gaps = ctx.job.fit_analysis.gaps if ctx.job.fit_analysis else []
    return [f"- {_clean(gap)}" for gap in gaps if str(gap).strip()]


def _put_in(ctx: StepContext) -> list[str]:
    lines = []
    if (ctx.job.cover_letter or "").strip():
        lines.append("- Cover letter: ready in the dossier")
    for answer in ctx.job.application_answers:
        if answer.needs_user_input:
            continue
        lines.append(f"- {_clean(answer.question)}")
        lines.append(f"  {_clean(answer.answer) or MISSING}")
    return lines


def _needs_harsh(ctx: StepContext) -> list[str]:
    lines = []
    for answer in ctx.job.application_answers:
        if answer.needs_user_input:
            why = _clean(answer.clarification)
            lines.append(f"- {_clean(answer.question)}" + (f": {why}" if why else ""))
    review = ctx.outputs.get("review") or {}
    if review.get("pass") is False:
        for issue in review.get("issues") or []:
            if isinstance(issue, dict):
                lines.append(_clean(
                    f"- Review, {issue.get('field', 'packet')}: {issue.get('problem', '')}"
                    + (f" (fix: {issue['fix']})" if issue.get("fix") else "")
                ))
    repaired = (ctx.outputs.get("repair") or {}).get("repaired") or []
    if repaired:
        lines.append(_clean("- Repaired once after review, check again: " + ", ".join(map(str, repaired))))
    form = ctx.outputs.get("form_fields") or {}
    if form.get("note"):
        lines.append(_clean(f"- Form not fully read: {form['note']}"))
    return lines


def _people(ctx: StepContext) -> list[str]:
    found = (ctx.outputs.get("people") or {}).get("people") or []
    lines = []
    for person in found:
        if isinstance(person, dict) and (person.get("name") or "").strip():
            bits = [person.get(key) for key in ("name", "title", "url") if (person.get(key) or "").strip()]
            lines.append("- " + _clean(", ".join(bits)))
    return lines


def _brief_text(ctx: StepContext) -> str:
    return "\n\n".join([
        _section("SUMMARY", _summary(ctx)),
        _section("APPLY AT", _apply_at(ctx)),
        _section("GAPS", _gaps(ctx)),
        _section("WHAT TO PUT IN", _put_in(ctx)),
        _section("NEEDS HARSH", _needs_harsh(ctx),
                 "nothing flagged" if ctx.job.application_answers or "review" in ctx.outputs else MISSING),
        _section("PEOPLE", _people(ctx)),
    ]) + "\n"


def brief_step(deps: tuple[str, ...] = (), mark_ready: bool = True) -> StepSpec:
    """`mark_ready=False` writes the brief only and leaves status alone, for a pipeline
    that has not run eligibility and fit_score yet (rule 2: no fit, no ready)."""

    def brief(ctx: StepContext) -> StepResult:
        writes: dict = {"research_brief": _brief_text(ctx)}
        status = ctx.job.status
        if mark_ready and status in _BRIEF_FROM:
            status = writes["status"] = "ready"
        return StepResult(output={"status": status}, writes=writes)

    owns = ("research_brief", "status") if mark_ready else ("research_brief",)
    return StepSpec("brief", "code", deps=deps, owns=owns, run=brief)


def code_steps(
    http: ats.Http | None = None, check: Check | None = None, *, mark_ready: bool = False
) -> tuple[StepSpec, ...]:
    """The code steps of section 4 as one chain, without the agent steps (the full
    chain is `pipelines.PACKET_PIPELINE`). Eligibility and fit_score have not run, so
    brief must not mark the dossier ready and `mark_ready` defaults to False."""
    return (*intake_steps(http, check), brief_step(deps=("liveness",), mark_ready=mark_ready))


def intake_steps(http: ats.Http | None = None, check: Check | None = None) -> tuple[StepSpec, ...]:
    """claim -> resolve_apply_url -> fetch_jd -> liveness. Resolving first (owner ruling,
    M4) means a board listing gets its JD and its liveness check from the employer ATS."""
    return (
        claim_step(),
        resolve_apply_url_step(http, deps=("claim",)),
        fetch_jd_step(http, deps=("resolve_apply_url",)),
        liveness_step(check, deps=("fetch_jd",)),
    )


# Code steps only, with the real network: for a live dry run on one dossier. The run
# ends packet_ready, but the dossier keeps its status and only gains a brief.
PACKET_CODE_PIPELINE = Pipeline("packet_code", code_steps())
