"""Records of the agent orchestrator: one run per dossier, the state of each of its
steps, and one attempt per try of a step. The attempts are the ledger that the stats
view and the router read to learn which adapter does which step well."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

RUN_STATUSES = (
    "queued",
    "running",
    "packet_ready",
    "retained_for_review",
    "ineligible",
    "closed_posting",
    "failed",
    "cancelled",
    # A task run (not per dossier, such as mail sync) that finished every step.
    "completed",
)
TERMINAL_STATUSES = frozenset(RUN_STATUSES[2:])

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]
Outcome = Literal["ok", "unavailable", "timeout", "invalid_output", "policy_violation", "error"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepState(BaseModel):
    status: StepStatus = "pending"
    output: dict | None = None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


class Run(BaseModel):
    id: str
    job_id: str
    pipeline: str
    status: str = "queued"
    # Postgres JSONB does not keep key order, so the step order is stored separately.
    order: list[str]
    steps: dict[str, StepState]
    terminal_reason: str = ""
    lease_owner: str = ""
    lease_until: str = ""
    created_at: str
    updated_at: str


class Attempt(BaseModel):
    id: str
    run_id: str
    job_id: str
    step: str
    adapter: str
    model: str = ""
    prompt_version: str = ""
    started_at: str
    duration_ms: int
    outcome: Outcome
    error: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    output_ref: str = ""


class AdapterResult(BaseModel):
    """What an adapter hands back for one try. `output` is the parsed JSON object the
    agent produced; the runner validates it against the step schema."""
    outcome: Outcome
    output: dict | None = None
    error: str = ""
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    # Where the raw agent output was saved on disk, for the attempt ledger.
    output_ref: str = ""
    # Version of prompts/<step>.md the adapter rendered ("" for the generic prompt).
    prompt_version: str = ""
