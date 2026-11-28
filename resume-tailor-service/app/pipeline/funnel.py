"""Funnel counts for the dashboard Flow tab: where every listing stands, by source,
region tier and stage, and a dated record of each bucket a listing was put in.

`funnel_events` is a small append only collection beside the pipeline runs (same
backend: Postgres when DATABASE_URL is set, a JSON file otherwise). The runner writes
one event when a step puts a dossier in a bucket (eligibility result, fit bucket) and
one when a dossier run ends (packet_ready, retained_for_review, ineligible and the other
terminal statuses); the research routes write one on promote and dismiss, and mail
sync one on a status change. The tree itself is built from current state; `since`
and `until` keep the listings created or moved (an event) in that window.

Region tiers come from `_tier_of`: an explicit `tier` field when the listing has one,
else `app.regions.classify_location` (the harvest's own rules) marked provisional.

Never call `record` from inside a job_store transaction: on SQL the store reuses that
transaction for any collection (see app/pipeline/store.py).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from app import job_store, research_store
from app.pipeline import store
from app.pipeline.models import now_iso
from app.pipeline.stats import as_utc, parse_since
from app.regions import classify_location

log = logging.getLogger(__name__)

FUNNEL = "funnel_events"
# The last harvest summary (scripts/remote_boards.harvest, from the CLI or the remote_boards task):
# {run_at, sources: {name: {fetched, kept: {A, A2, E}, dropped: {reason: n}}}}.
HARVEST_DIR = Path(__file__).resolve().parents[2] / "data"
HARVEST_FILE = "remote_candidates.summary.json"
TOP_JOBS = 10

# --- events -----------------------------------------------------------------------------


def record(bucket: str, *, job_id: str = "", item_id: str = "", source: str = "", step: str = "",
           run_id: str = "", detail: str = "", at: str = "") -> dict:
    event = {
        "id": uuid.uuid4().hex,
        "at": at or now_iso(),
        "bucket": bucket,
        "job_id": job_id,
        "item_id": item_id,
        "source": source_key(source) if source else "",
        "step": step,
        "run_id": run_id,
        "detail": detail[:300],
    }
    with store._store(FUNNEL).transaction(FUNNEL) as tx:
        tx.put(event, {"status": bucket, "match_key": job_id or item_id, "sort_key": event["at"]})
    return event


def record_safely(bucket: str, **fields) -> None:
    """record(), but a failing event store is logged and never breaks the caller: the
    events are a report, not part of the work."""
    try:
        record(bucket, **fields)
    except Exception:
        log.exception("could not record funnel event %s", bucket)


def _in_range(at: str, since: datetime | None, until: datetime | None) -> bool:
    try:
        moment = as_utc(at)
    except (TypeError, ValueError):
        return False
    return (since is None or moment >= since) and (until is None or moment < until)


def list_events(since: str = "", until: str = "") -> list[dict]:
    """Events in [since, until), oldest first. A date means its midnight UTC; raises
    ValueError for a value that is not an ISO 8601 date or time."""
    start, end = parse_since(since), parse_since(until)
    events = [e for e in store._store(FUNNEL).all(FUNNEL) if _in_range(e.get("at", ""), start, end)]
    return sorted(events, key=lambda e: e.get("at", ""))


# Step outputs that put a dossier in a bucket.
def step_bucket(step: str, output: dict, stop: str) -> str:
    if step == "eligibility":
        return "eligible" if output.get("eligible") else "ineligible"
    if step == "fit_score":
        return "retained" if stop == "retained_for_review" else "fit_passed"
    return ""


# --- sources ----------------------------------------------------------------------------

_SOURCE_PATTERNS = (
    (r"linkedin", "linkedin"),
    (r"wellfound|angel\.?co|angellist", "wellfound"),
    (r"remotive", "remotive"),
    (r"himalayas", "himalayas"),
    (r"jobicy", "jobicy"),
    (r"working\s*nomads", "working_nomads"),
    (r"remote\s*ok", "remote_ok"),
    (r"ziprecruiter", "ziprecruiter"),
    (r"work\s*at\s*a\s*startup|\byc\b|y\s*combinator", "yc"),
    (r"fantastic", "fantastic_jobs"),
    (r"watchlist|greenhouse|\blever\b|ashby|\bats\b", "ats_watchlist"),
    (r"job_registry", "job_registry"),
)
SOURCE_LABELS = {
    "linkedin": "LinkedIn", "wellfound": "Wellfound", "remotive": "Remotive", "himalayas": "Himalayas",
    "jobicy": "Jobicy", "working_nomads": "Working Nomads", "remote_ok": "Remote OK",
    "ziprecruiter": "ZipRecruiter", "yc": "YC Work at a Startup", "fantastic_jobs": "Fantastic Jobs",
    "ats_watchlist": "ATS watchlist", "job_registry": "Job registry (old)", "manual": "Manual or unknown",
}


def source_key(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "manual"
    for pattern, key in _SOURCE_PATTERNS:
        if re.search(pattern, text):
            return key
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "manual"


def _source_label(key: str) -> str:
    return SOURCE_LABELS.get(key) or key.replace("_", " ").title()


# --- region tier ------------------------------------------------------------------------

TIERS = ("A", "A2", "E", "unknown", "excluded")
TIER_LABELS = {
    "A": "Tier A, open to Canada",
    "A2": "Tier A2, US, UK, Australia, New Zealand or another country",
    "E": "Tier E, Europe (last)",
    "unknown": "Region unknown",
    "excluded": "Outside the region policy (India or not remote)",
    "dropped": "Dropped by the region filter",
}
# Exact tier tokens a pipeline step or a research promotion wrote into the notes.
_NOTES_TIER = re.compile(r"\bTier (A2|A|E)\b")


def _tier_of(item: dict) -> tuple[str, bool]:
    """(tier, provisional). An explicit `tier` field wins (the harvest and research staging
    mark one). Else the newest exact tier token in the notes, else
    app.regions.classify_location on the location, remote scope and job description. Any
    tier not read from the `tier` field is provisional. A listing the classifier drops
    (India, not remote) is "excluded"; one with no location at all is "unknown"."""
    explicit = str(item.get("tier") or "").strip()
    if explicit:
        upper = explicit.upper()
        if upper in ("A", "A2", "E"):
            return upper, False
        return ("excluded" if explicit.lower() == "drop" else explicit.lower()), False
    noted = _NOTES_TIER.findall(str(item.get("notes") or ""))
    if noted:
        return noted[-1], True
    location = str(item.get("location") or "").strip()
    scope = str(item.get("remote_scope") or "").strip()
    if not location and not scope:
        return "unknown", True
    description = str(item.get("jd_text") or item.get("description") or "")
    where = classify_location(location, scope, description=description)
    return ("excluded" if where.tier == "drop" else where.tier), True


# --- stages -----------------------------------------------------------------------------

STAGES = (
    ("research_new", "Research, new"),
    ("dismissed", "Research, dismissed"),
    ("promoted", "Promoted from research"),
    ("discovered", "Discovered, not scored"),
    ("in_pipeline", "Packet run queued or running"),
    ("run_failed", "Packet run failed or cancelled, needs a look"),
    ("ineligible", "Ineligible"),
    ("retained", "Retained for review, fit too low"),
    ("eligible", "Eligible, fit 6 or more"),
    ("ready", "Ready"),
    ("packet_ready", "Packet ready"),
    ("applying", "Applying"),
    ("applied", "Applied"),
    ("outreach", "Outreach"),
    ("interview", "Interview"),
    ("offer", "Offer"),
    ("rejected", "Rejected"),
    ("closed", "Posting closed"),
    ("skipped", "Skipped"),
    ("archived", "Archived"),
)
STAGE_LABELS = dict(STAGES)
_PAST_PACKET = frozenset({"applying", "applied", "outreach", "interview", "offer", "rejected", "skipped", "archived"})
_RUN_STAGE = {"packet_ready": "packet_ready", "ineligible": "ineligible",
              "retained_for_review": "retained", "closed_posting": "closed",
              "queued": "in_pipeline", "running": "in_pipeline",
              "failed": "run_failed", "cancelled": "run_failed"}


def stage_of(job: dict, run_status: str) -> str:
    """Where a dossier stands now: its own status once it is past the packet, else the
    result of its newest packet run, else its status and fit score."""
    status = job.get("status") or "discovered"
    if status in _PAST_PACKET:
        return status
    if run_status in _RUN_STAGE:
        return _RUN_STAGE[run_status]
    if status == "ready":
        return "ready"
    fit = job.get("fit_score")
    if isinstance(fit, int):
        return "eligible" if fit >= job_store.FIT_APPLY_FLOOR else "retained"
    return "discovered"


# --- harvest ----------------------------------------------------------------------------


def _harvest(since: datetime | None = None, until: datetime | None = None) -> tuple[dict[str, dict], dict | None]:
    """Per source {fetched, kept: {tier: n}, dropped: {reason: n}} from the last harvest
    summary, and its totals; ({}, None) when there is none, it is unreadable, or a date
    range is set and the harvest ran outside it."""
    per_source: dict[str, dict] = {}
    run_at = ""
    found = False
    path = HARVEST_DIR / HARVEST_FILE
    for path in [path] if path.is_file() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sources = data.get("sources") or {}
            if not isinstance(sources, dict):
                continue
        except (OSError, ValueError, AttributeError):
            log.warning("ignoring unreadable harvest summary %s", path)
            continue
        found = True
        run_at = max(run_at, str(data.get("run_at") or ""))
        for name, raw in sources.items():
            if not isinstance(raw, dict):
                continue
            entry = per_source.setdefault(source_key(name), {"fetched": 0, "kept": {}, "dropped": {}})
            entry["fetched"] += _int(raw.get("fetched"))
            for tier, n in (raw.get("kept") or {}).items():
                key = _tier_of({"tier": tier})[0]
                entry["kept"][key] = entry["kept"].get(key, 0) + _int(n)
            for reason, n in (raw.get("dropped") or {}).items():
                entry["dropped"][str(reason)] = entry["dropped"].get(str(reason), 0) + _int(n)
    if not found or ((since or until) and not _in_range(run_at, since, until)):
        return {}, None
    totals = {
        "run_at": run_at,
        "fetched": sum(e["fetched"] for e in per_source.values()),
        "kept": sum(sum(e["kept"].values()) for e in per_source.values()),
        "dropped": sum(sum(e["dropped"].values()) for e in per_source.values()),
    }
    return per_source, totals


def _int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# --- the tree ---------------------------------------------------------------------------

_JOB_FIELDS = ("id", "company", "role", "source", "location", "work_mode", "status", "fit_score", "notes",
               "created_at", "updated_at", "tier", "jd_text")


def _latest_packet_runs() -> dict[str, str]:
    latest: dict[str, str] = {}
    for run in store.list_runs():  # newest first
        if run.pipeline == "packet" and run.job_id not in latest:
            latest[run.job_id] = run.status
    return latest


def _records() -> list[dict]:
    """Every listing once: each dossier, and each research item not yet a dossier."""
    runs = _latest_packet_runs()
    records: list[dict] = []
    dossier_ids: set[str] = set()
    for job in job_store._store().fields(job_store._COLLECTION, _JOB_FIELDS):
        if not job.get("id"):
            continue
        dossier_ids.add(job["id"])
        tier, provisional = _tier_of(job)
        records.append({
            "id": job["id"], "kind": "dossier", "company": job.get("company") or "", "role": job.get("role") or "",
            "source": source_key(job.get("source")), "tier": tier, "provisional": provisional,
            "stage": stage_of(job, runs.get(job["id"], "")), "status": job.get("status") or "",
            "fit_score": job.get("fit_score"), "at": job.get("created_at") or "",
        })
    for item in research_store.list_items():
        if item.get("status") == "promoted" and item.get("dossier_id") in dossier_ids:
            continue  # counted as its dossier
        tier, provisional = _tier_of(item)
        stage = {"new": "research_new", "dismissed": "dismissed", "promoted": "promoted"}.get(
            item.get("status") or "new", "research_new")
        records.append({
            "id": item.get("id") or "", "kind": "research", "company": item.get("company") or "",
            "role": item.get("role") or "", "source": source_key(item.get("source")), "tier": tier,
            "provisional": provisional, "stage": stage, "status": item.get("status") or "new",
            "fit_score": None, "at": item.get("found_at") or "",
        })
    return records


def _leaf(record: dict) -> dict:
    return {
        "key": record["id"], "label": f"{record['company']}, {record['role']}", "kind": "job", "count": 1,
        "job": {"id": record["id"], "company": record["company"], "role": record["role"],
                "fit_score": record["fit_score"], "status": record["status"],
                "dossier": record["kind"] == "dossier"},
        "children": [],
    }


def _top(records: list[dict]) -> list[dict]:
    ranked = sorted(records, key=lambda r: (-(r["fit_score"] or 0), r["company"].lower(), r["role"].lower()))
    return [_leaf(r) for r in ranked[:TOP_JOBS]]


def _stage_nodes(records: list[dict]) -> list[dict]:
    nodes = []
    for key, label in STAGES:
        group = [r for r in records if r["stage"] == key]
        if group:
            nodes.append({"key": key, "label": label, "kind": "stage", "count": len(group),
                          "children": _top(group)})
    return nodes


def _tier_order(key: str) -> int:
    return TIERS.index(key) if key in TIERS else len(TIERS)


def build(since: str = "", until: str = "") -> dict:
    """The funnel tree. Raises ValueError for a bad since or until."""
    start, end = parse_since(since), parse_since(until)
    events = list_events(since, until) if (start or end) else []
    records = _records()
    if start or end:
        moved = {e.get("job_id") for e in events} | {e.get("item_id") for e in events}
        moved.discard("")
        records = [r for r in records if r["id"] in moved or _in_range(r["at"], start, end)]
    harvest, totals = _harvest(start, end)

    by_source: dict[str, list[dict]] = {}
    for record_ in records:
        by_source.setdefault(record_["source"], []).append(record_)
    for name in harvest:
        by_source.setdefault(name, [])

    tree = []
    for name, group in by_source.items():
        tiers: dict[str, list[dict]] = {}
        for record_ in group:
            tiers.setdefault(record_["tier"], []).append(record_)
        info = harvest.get(name) or {"fetched": None, "kept": {}, "dropped": {}}
        for tier in info["kept"]:
            tiers.setdefault(tier, [])
        children = []
        for tier in sorted(tiers, key=lambda t: (_tier_order(t), t)):
            members = tiers[tier]
            node = {"key": tier, "label": TIER_LABELS.get(tier, f"Tier {tier}"), "kind": "tier",
                    "count": len(members), "provisional": any(r["provisional"] for r in members),
                    "children": _stage_nodes(members)}
            if tier in info["kept"]:
                node["kept"] = info["kept"][tier]
            children.append(node)
        dropped_total = sum(info["dropped"].values())
        if info["dropped"]:
            children.append({
                "key": "dropped", "label": TIER_LABELS["dropped"], "kind": "dropped", "count": dropped_total,
                "children": [{"key": reason, "label": reason, "kind": "reason", "count": n, "children": []}
                             for reason, n in sorted(info["dropped"].items(), key=lambda kv: (-kv[1], kv[0]))],
            })
        node = {"key": name, "label": _source_label(name), "kind": "source", "count": len(group),
                "children": children}
        if info["fetched"] is not None:
            node["fetched"] = info["fetched"]
            node["dropped"] = dropped_total
        tree.append(node)
    tree.sort(key=lambda n: (-n["count"], -(n.get("fetched") or 0), n["label"].lower()))

    stages = {key: 0 for key, _ in STAGES}
    tier_counts = {key: 0 for key in TIERS}
    for record_ in records:
        stages[record_["stage"]] = stages.get(record_["stage"], 0) + 1
        tier_counts[record_["tier"]] = tier_counts.get(record_["tier"], 0) + 1
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event["bucket"]] = event_counts.get(event["bucket"], 0) + 1
    return {
        "since": since, "until": until, "generated_at": now_iso(), "total": len(records),
        "stages": stages, "stage_labels": STAGE_LABELS, "tiers": tier_counts,
        "harvest": totals, "events": event_counts, "tree": tree,
    }
