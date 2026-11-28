"""Task pipelines: scheduled work that belongs to no single dossier (spec 13.3).

    mail_sync       mail_fetch -> mail_classify (agent, cheap) -> mail_apply -> mail_report
    liveness_sweep  liveness_sweep           (code, report only, never deletes)
    remote_boards   remote_boards_harvest    (code, scripts/remote_boards.harvest)
    ats_watchlist   ats_watchlist_poll       (code, scripts/ats_watchlist.poll)

They run on the normal runner with `scope="task"` (see runner.py), so leases, resume,
the attempt ledger and the adapter chain are shared with the packet pipeline. Only
`mail_classify` uses a model; everything else is plain code that reuses the existing
scripts rather than rewriting them.

Mail sync follows prompts/mail-sync.md: two searches from two days before the newest
message of the last completed run, one event per application email, matched to a
dossier by `scripts/mail_outcomes.plan` and written as an activity keyed on the Gmail
message id, so a rerun never writes the same email twice. Uncertain events are held,
unmatched and ambiguous ones are reported, and no dossier is ever created here.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, field_validator

from app import job_store, session_store
from app.house_style import strip_dashes
from app.mail import gmail
from app.mail import store as mail_store
from app.models import JobActivityInput, SessionEventInput
from app.pipeline import funnel, prompts, runner, steps_code, store
from app.pipeline.models import Run, now_iso
from app.pipeline.runner import Pipeline, StepContext, StepResult, StepSpec, task_job_id

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
WATCHLIST = Path(__file__).resolve().parents[2] / "content" / "ats_watchlist.yaml"

MAIL_SYNC = "mail_sync"
LIVENESS_SWEEP = "liveness_sweep"
REMOTE_BOARDS = "remote_boards"
ATS_WATCHLIST = "ats_watchlist"

FIRST_RUN_DAYS = 14
OVERLAP_DAYS = 2  # prompts/mail-sync.md: two days before the last run's newest date
MAX_MESSAGES = 100
LIVENESS_STATUSES = frozenset({"discovered", "researching", "ready"})
LIVENESS_AGE_DAYS = 30
LIVENESS_LIMIT = 200

_SCRIPTS: dict[str, object] = {}


def load_script(name: str):
    """A module from scripts/ (not a package), loaded once by path."""
    if name not in _SCRIPTS:
        path = SCRIPTS / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"job_machine_scripts_{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _SCRIPTS[name] = module
    return _SCRIPTS[name]


def _line(text: object) -> str:
    return " ".join(strip_dashes(str(text or "")).split())


# --- mail sync -------------------------------------------------------------------------


class MailEvent(BaseModel):
    """One event, the shape prompts/mail-sync.md step 3 defines."""
    id: str
    company: str
    role: str = ""
    date: str = ""
    outcome: Literal["rejected", "interview", "assessment", "reply"]
    confident: bool
    note: str = ""

    @field_validator("id", "company")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = _line(value)
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("role", "note")
    @classmethod
    def _one_line(cls, value: str) -> str:
        return _line(value)


class MailClassifyOutput(BaseModel):
    events: list[MailEvent]


def mail_window(state: dict, today: date | None = None) -> date:
    today = today or datetime.now(timezone.utc).date()
    newest = state.get("newest_date")
    if newest:
        try:
            return date.fromisoformat(newest) - timedelta(days=OVERLAP_DAYS)
        except ValueError:
            pass
    return today - timedelta(days=FIRST_RUN_DAYS)


def _instructions() -> str:
    """The classify prompt for adapters that show step outputs but do not yet render
    prompts/<step>.md; the messages follow in the same output."""
    return prompts.template_source("mail_classify").replace(
        "{{outputs}}", "(see `messages` in this same step output)"
    )


def mail_fetch_step(client_factory: Callable[[], gmail.GmailClient] | None = None,
                    today: Callable[[], date] | None = None) -> StepSpec:
    def fetch(ctx: StepContext) -> StepResult:
        after = mail_window(mail_store.get_state(), today() if today else None)
        client = (client_factory or gmail.default_client)()
        messages, known, receipts = client.fetch(after, skip=mail_store.known_ids(), limit=MAX_MESSAGES)
        return StepResult(output={
            "after": after.isoformat(),
            "known": known,
            "messages": [m.to_dict() for m in messages],
            # Receipts and codes: never shown to the agent, only marked seen.
            "receipts": [{k: v for k, v in m.to_dict().items() if k not in ("body", "snippet")} for m in receipts],
            "instructions": _instructions(),
        })

    return StepSpec("mail_fetch", "code", run=fetch)


def _fetched(ctx: StepContext) -> list[dict]:
    return (ctx.outputs.get("mail_fetch") or {}).get("messages") or []


def _finish_classify(out: MailClassifyOutput, ctx: StepContext) -> StepResult:
    """Keep only events about fetched messages, once each, dated by the message itself:
    the agent classifies, it never supplies ids or dates of its own."""
    fetched = {m["id"]: m for m in _fetched(ctx)}
    events, dropped, seen = [], [], set()
    for event in out.events:
        if event.id not in fetched or event.id in seen:
            dropped.append(event.id)
            continue
        seen.add(event.id)
        events.append({**event.model_dump(), "date": fetched[event.id]["date"] or event.date})
    return StepResult(output={"events": events, "dropped": dropped})


def mail_classify_step() -> StepSpec:
    return StepSpec("mail_classify", "agent", deps=("mail_fetch",), capability="cheap",
                    schema=MailClassifyOutput, finish=_finish_classify,
                    when=lambda ctx: bool(_fetched(ctx)))


def _mirror(job_id: str, data: JobActivityInput) -> None:
    """Copy the activity to the session log, as POST /api/jobs/{id}/activity does."""
    try:
        session_store.append_event(SessionEventInput(
            session=data.session, kind=data.kind, title=data.title, detail=data.detail,
            job_id=job_id, occurred_at=data.occurred_at, external_id=data.external_id,
        ))
    except OSError:
        pass


def _write(event: dict, decision: dict, session: str, run_id: str) -> tuple[str, str]:
    """Write one matched event. Returns (status, status change). The activity check, the
    activity and the status move are one dossier transaction: a rerun or a second run
    cannot apply the same email twice, and a crash cannot keep the activity and lose the
    status move (the next run would then see a duplicate and never move it)."""
    outcomes = load_script("mail_outcomes")
    job_id = decision["job"]["id"]
    data = JobActivityInput(**outcomes.activity(event, session))
    change = decision["set_status"] or ""
    with job_store._transaction():
        updated, refused = job_store.add_activity_unless(
            job_id, data,
            lambda current: "duplicate" if any(a.external_id == data.external_id for a in current.activities) else "",
        )
        if updated is None:
            return "unmatched", ""
        if refused:
            return "duplicate", ""
        if change:
            job_store.patch_job(job_id, {"status": change},
                                reason=f"Mail sync {run_id}: {event['outcome']} email", session=session)
    _mirror(job_id, data)
    if change:
        funnel.record_safely(change, job_id=job_id, step="mail_sync", run_id=run_id,
                             source=getattr(job_store.get_job(job_id), "source", ""))
    return "written", change


def mail_apply_step() -> StepSpec:
    def apply(ctx: StepContext) -> StepResult:
        outcomes = load_script("mail_outcomes")
        messages = {m["id"]: m for m in _fetched(ctx)}
        events = sorted((ctx.outputs.get("mail_classify") or {}).get("events") or [],
                        key=lambda e: (e["date"], e["id"]))
        jobs = [summary.model_dump() for summary in job_store.list_summaries()]
        by_id = {job["id"]: job for job in jobs}
        session = f"Mail sync {ctx.run.id}"
        records = []
        for event in events:
            message = messages.get(event["id"], {})
            decision = outcomes.plan(event, jobs, by_id)
            job = decision["job"]
            record = {
                **event,
                "subject": message.get("subject", ""), "sender": message.get("sender", ""),
                "thread_id": message.get("thread_id", ""), "run_id": ctx.run.id,
                "reason": decision["reason"], "status_change": "",
                "dossier_id": job["id"] if job else "",
                "dossier": f"{job['company']} / {job['role']}" if job else "",
            }
            if decision["action"] == "write":
                record["status"], record["status_change"] = _write(event, decision, session, ctx.run.id)
                if record["status_change"]:
                    by_id[job["id"]]["status"] = record["status_change"]
            else:
                record["status"] = decision["action"]
            records.append(record)
        classified = {event["id"] for event in events}
        receipts = (ctx.outputs.get("mail_fetch") or {}).get("receipts") or []
        unclassified = [(m, "not about an application") for m in messages.values() if m["id"] not in classified]
        for message, reason in unclassified + [(m, "receipt or sign in code") for m in receipts]:
            # Stored as seen so the next run neither opens nor classifies it again.
            records.append({
                "id": message["id"], "company": "", "role": "", "date": message["date"],
                "outcome": "", "confident": True, "note": "", "status": "ignored",
                "subject": message["subject"], "sender": message["sender"],
                "thread_id": message["thread_id"], "run_id": ctx.run.id,
                "reason": reason, "status_change": "", "dossier_id": "", "dossier": "",
            })
        mail_store.save_events(records)
        keep = ("id", "company", "role", "date", "outcome", "confident", "note", "status",
                "status_change", "dossier_id", "dossier", "reason", "subject", "sender")
        return StepResult(output={"results": [{k: r.get(k) for k in keep} for r in records]})

    return StepSpec("mail_apply", "code", deps=("mail_classify",), run=apply)


def mail_report_step() -> StepSpec:
    def report(ctx: StepContext) -> StepResult:
        fetch = ctx.outputs.get("mail_fetch") or {}
        results = (ctx.outputs.get("mail_apply") or {}).get("results") or []
        relevant = [r for r in results if r["status"] != "ignored"]

        def brief(r: dict) -> dict:
            return {k: r.get(k) for k in ("id", "date", "company", "role", "outcome", "note", "status",
                                          "dossier_id", "reason")}

        state = mail_store.get_state()
        dates = [m["date"] for m in fetch.get("messages") or [] if m.get("date")]
        newest = max(dates + [state.get("newest_date") or ""]) or None
        counts = dict(Counter(r["status"] for r in results))
        output = {
            "after": fetch.get("after", ""),
            "fetched": len(fetch.get("messages") or []),
            "already_seen": fetch.get("known", 0),
            # prompts/mail-sync.md step 5 order: what waits on Harsh, new interviews, counts.
            "waiting_on_harsh": [brief(r) for r in relevant if r["outcome"] == "assessment"],
            "interviews": [brief(r) for r in relevant if r["outcome"] == "interview"],
            "rejections_written": sum(1 for r in results if r["outcome"] == "rejected" and r["status"] == "written"),
            "counts": counts,
            "held": [brief(r) for r in relevant if r["status"] == "held"],
            "unmatched": [brief(r) for r in relevant if r["status"] == "unmatched"],
            # AGENTS.md: interviews and rejections also go to the Sheet; an agent logs these.
            # AGENTS.md rule 7 also covers replies.
            "sheet_log": [brief(r) for r in relevant
                          if r["status"] == "written" and r["outcome"] in ("interview", "rejected", "reply")],
            # Left out by the model: stored as seen, so listed here for a human glance.
            "ignored": [{k: r.get(k) for k in ("id", "date", "subject", "sender")} for r in results
                        if r["status"] == "ignored" and r.get("reason") == "not about an application"],
            "newest_date": newest,
        }
        # The window moves only here, after every step before it finished.
        mail_store.save_state(newest_date=newest, last_run_id=ctx.run.id, last_run_at=now_iso(), last_counts=counts)
        return StepResult(output=output)

    return StepSpec("mail_report", "code", deps=("mail_apply",), run=report)


def mail_sync_pipeline(client_factory: Callable[[], gmail.GmailClient] | None = None,
                       today: Callable[[], date] | None = None) -> Pipeline:
    return Pipeline(MAIL_SYNC, (
        mail_fetch_step(client_factory, today),
        mail_classify_step(),
        mail_apply_step(),
        mail_report_step(),
    ), done_status="completed", scope="task")


# --- update checks ---------------------------------------------------------------------


def _created(summary) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(summary.created_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def liveness_sweep_pipeline(check: steps_code.Check | None = None, *,
                            older_than_days: int = LIVENESS_AGE_DAYS, limit: int = LIVENESS_LIMIT) -> Pipeline:
    def sweep(ctx: StepContext) -> StepResult:
        check_url = check or steps_code._default_check()
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        candidates = []
        for summary in job_store.list_summaries():
            created = _created(summary)
            if summary.status in LIVENESS_STATUSES and summary.job_url and created and created <= cutoff:
                candidates.append(summary)
        candidates.sort(key=lambda s: s.created_at)
        counts: Counter = Counter()
        closed = []
        for summary in candidates[:limit]:
            try:
                state, evidence = check_url(summary.job_url)
            except Exception as exc:  # a broken check is "unknown", never "closed"
                state, evidence = "unknown", f"{type(exc).__name__}"
            counts[state] += 1
            if state == "closed":
                closed.append({"id": summary.id, "company": summary.company, "role": summary.role,
                               "status": summary.status, "url": summary.job_url, "evidence": evidence})
        # Report only: a closed posting is listed for Harsh, never deleted or archived.
        return StepResult(output={"older_than_days": older_than_days, "eligible": len(candidates),
                                  "checked": min(len(candidates), limit), "counts": dict(counts),
                                  "closed": closed})

    return Pipeline(LIVENESS_SWEEP, (StepSpec("liveness_sweep", "code", run=sweep),),
                    done_status="completed", scope="task")


def remote_boards_pipeline(boards=None, *, days: int = 21, out_path: Path | None = None) -> Pipeline:
    def refresh(ctx: StepContext) -> StepResult:
        from app.pipeline import funnel

        module = load_script("remote_boards")
        # Default: where the Flow tab (GET /api/pipeline/funnel) reads the last harvest.
        path = out_path or funnel.HARVEST_DIR / "remote_candidates.json"
        kept, summary = module.harvest(boards, days=days, out=path)
        sources = summary["sources"].values()
        dropped: dict[str, int] = {}
        kept_by_tier = {tier: 0 for tier in module.TIERS}
        for counts in sources:
            for reason, n in counts["dropped"].items():
                dropped[reason] = dropped.get(reason, 0) + n
            for tier, n in counts["kept"].items():
                kept_by_tier[tier] = kept_by_tier.get(tier, 0) + n
        per_board = {name: (f"failed: {counts['error']}"[:200] if "error" in counts else counts["fetched"])
                     for name, counts in summary["sources"].items()}
        listed = [{k: row.get(k, "") for k in ("company", "role", "job_url", "source", "location", "posted",
                                                "tier", "region", "company_history")} for row in kept]
        # Harvest only: scoring and capture stay agent steps (AGENTS.md), so no dossier is written.
        return StepResult(output={"fetched": sum(c["fetched"] for c in sources), "kept": len(listed),
                                  "kept_by_tier": kept_by_tier, "dropped": dropped, "boards": per_board,
                                  "candidates_file": str(path), "summary_file": str(module.summary_path(path)),
                                  "listings": listed})

    return Pipeline(REMOTE_BOARDS, (StepSpec("remote_boards_harvest", "code", run=refresh),),
                    done_status="completed", scope="task")


def _in_process(url: str, method: str = "GET", payload: dict | None = None) -> object:
    """The two service routes ats_watchlist.poll calls, answered in process."""
    from app.search import _DASHBOARD_HEADER, ResearchItem, add_research

    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
    if method == "GET" and path == "/api/jobs":
        return [summary.model_dump() for summary in job_store.list_summaries()]
    if method == "POST" and path == "/api/research":
        return add_research(ResearchItem(**(payload or {})), x_job_machine=_DASHBOARD_HEADER)
    raise ValueError(f"unexpected service call {method} {path}")


def ats_watchlist_pipeline(get_json: Callable[[str], object] | None = None, *,
                           watchlist: Path | None = None) -> Pipeline:
    def poll(ctx: StepContext) -> StepResult:
        module = load_script("ats_watchlist")
        boards = module.load_watchlist(watchlist or WATCHLIST)
        # Discovery only: new listings are staged in the Research queue, as the script does.
        result = module.poll(boards, "http://in-process", get_json=get_json or module._get_json,
                             request_json=_in_process)
        return StepResult(output={"boards": len(boards), **result})

    return Pipeline(ATS_WATCHLIST, (StepSpec("ats_watchlist_poll", "code", run=poll),),
                    done_status="completed", scope="task")


# --- registry --------------------------------------------------------------------------

TASK_BUILDERS: dict[str, Callable[..., Pipeline]] = {
    MAIL_SYNC: mail_sync_pipeline,
    LIVENESS_SWEEP: liveness_sweep_pipeline,
    REMOTE_BOARDS: remote_boards_pipeline,
    ATS_WATCHLIST: ats_watchlist_pipeline,
}


def task_pipeline(name: str, **deps) -> Pipeline:
    if name not in TASK_BUILDERS:
        raise KeyError(f"no task pipeline {name!r}")
    return TASK_BUILDERS[name](**deps)


def active_run(name: str) -> Run | None:
    """A queued or running run of this task pipeline, if any."""
    for run in store.list_runs(task_job_id(name)):
        if run.status in ("queued", "running"):
            return run
    return None


def enqueue(name: str) -> Run:
    pipeline = task_pipeline(name)
    return store.create_run(task_job_id(name), name, pipeline.order)


_ENQUEUE_LOCK = threading.Lock()


def enqueue_if_idle(name: str) -> tuple[Run | None, Run | None]:
    """Queue a run unless one is queued or running: (new run, None) or (None, active).
    The API and the worker's schedules both go through here, so in one service process
    they cannot queue the same task twice."""
    with _ENQUEUE_LOCK:
        active = active_run(name)
        if active is not None:
            return None, active
        return enqueue(name), None


def _default_chain():
    from app.pipeline.router import Health, make_chain

    return make_chain(health=Health())


def run_task(name: str, *, owner: str = "run_task", pipeline: Pipeline | None = None,
             resolve_chain: runner.Chain | None = None, run_id: str | None = None) -> Run:
    """Run a task pipeline now, in this process: a new run, or a queued one by id."""
    pipeline = pipeline or task_pipeline(name)
    if run_id is None:
        run_id = store.create_run(task_job_id(name), name, pipeline.order).id
    chain = resolve_chain or _default_chain()
    return runner.run(run_id, pipeline, owner=owner, resolve_chain=chain)
