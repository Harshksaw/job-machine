# Inbox and Session Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the existing Inbox, session narrative, and job-specific people work as a backward-compatible, concurrency-safe Job Machine release.

**Architecture:** The dossier JSON store remains the only source of job state. A server-side decision command updates only decision fields under the existing store lock; people associations are resolved by one shared matcher; explicit activities and Inbox mutations mirror into an append-only session JSONL log. The React dashboard consumes summary fields and command endpoints, then ships as committed Vite assets.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, pytest, React 18, TypeScript 5, Vite 5, Tailwind CSS 3

**Spec:** `docs/superpowers/specs/2026-08-27-inbox-session-integration-design.md`

## Global Constraints

- Preserve every pre-existing user-owned change in the dirty working tree.
- Do not stage or commit files during this pass; unrelated changes appeared while the integration was being reviewed.
- Keep existing `data/jobs.json` and `data/people.json` records valid without a migration.
- Keep the service loopback-only and unauthenticated; do not expose it on a network.
- Do not upgrade major Python or Node dependencies.
- Do not build the SQLite tailoring queue, review console, or canonical resume verifier.
- Keep `data/` and `backups/` ignored; commit only generated dashboard assets under `app/static/` when the user later chooses to commit.

---

### Task 1: Atomic Inbox decision command

**Files:**
- Modify: `resume-tailor-service/app/models.py`
- Modify: `resume-tailor-service/app/job_store.py`
- Modify: `resume-tailor-service/app/jobs.py`
- Modify: `resume-tailor-service/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `JobWorkspace`, `JobWorkspaceInput`, `JobActivityInput`, and the existing JSON-store `RLock`.
- Produces: `JobDecisionInput(decision, session)` and `job_store.apply_decision(job_id, decision, session) -> JobWorkspace | None`.
- Produces: `POST /api/jobs/{job_id}/decision -> JobWorkspace`.

- [x] **Step 1: Isolate session persistence in the jobs API fixture**

Import `session_store` in `tests/test_jobs_api.py` and point it at the test directory:

```python
from app import application_kit, job_store, jobs, people_store, session_store, sheets

def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
```

- [x] **Step 2: Write failing decision-contract tests**

Add `import pytest` and import `JobWorkspaceInput`. Then add a parametrized test that creates a job with notes and a cover letter, calls the decision endpoint, and asserts only decision fields changed:

```python
@pytest.mark.parametrize(
    ("decision", "status", "next_action"),
    [
        ("approve", "ready", "Apply; reach out to people at the company"),
        ("hold", "researching", "Review later"),
        ("applied", "applied", "Reach out to people at the company"),
    ],
)
def test_inbox_decision_is_atomic_and_preserves_dossier(
    monkeypatch, tmp_path, decision, status, next_action
):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    payload = {key: job[key] for key in JobWorkspaceInput.model_fields}
    payload.update({"fit_score": 8, "notes": "new agent research", "cover_letter": "Dear team"})
    saved = client.put(f"/api/jobs/{job['id']}", json=payload).json()

    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": decision, "session": "Inbox 2026-08-27"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    assert body["next_action"] == next_action
    assert body["notes"] == "new agent research"
    assert body["cover_letter"] == "Dear team"
    assert body["activities"][-1]["session"] == "Inbox 2026-08-27"
    assert set(body["revisions"][-1]["changed_fields"]) <= {"status", "next_action"}
```

Also assert `{"decision": "delete"}` returns HTTP 422 and does not change the dossier.

- [x] **Step 3: Run the decision tests and confirm the route is absent**

Run: `uv run pytest tests/test_jobs_api.py -k inbox_decision -q`

Expected before implementation: FAIL because `/api/jobs/{id}/decision` returns 404.

- [x] **Step 4: Add the validated decision input model**

In `app/models.py`, define the exact command vocabulary and strip its session label:

```python
JOB_DECISIONS = ("approve", "hold", "applied")

class JobDecisionInput(BaseModel):
    decision: str
    session: str = "Inbox"

    @field_validator("decision")
    @classmethod
    def _known_decision(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in JOB_DECISIONS:
            raise ValueError(f"decision must be one of {JOB_DECISIONS}")
        return value

    @field_validator("session")
    @classmethod
    def _clean_session(cls, value: str) -> str:
        return value.strip()
```

- [x] **Step 5: Implement the locked, field-limited store mutation**

In `app/job_store.py`, add a decision map and an `apply_decision` function that performs one read/write under `_LOCK`. Build the new `JobWorkspaceInput` from the current record, patch only `status` and `next_action`, append one activity and one revision, and preserve all other fields:

```python
_DECISION_PATCH = {
    "approve": ("ready", "Apply", "decision", "Approved to apply"),
    "hold": ("researching", "Review later", "decision", "Held for later review"),
    "applied": ("applied", "Await response", "applied", "Marked applied from inbox"),
}

def apply_decision(job_id: str, decision: str, *, session: str = "Inbox") -> JobWorkspace | None:
    with _LOCK:
        items = _read_unlocked()
        for index, raw in enumerate(items):
            try:
                current = JobWorkspace.model_validate(raw)
            except ValueError:
                continue
            if current.id != job_id:
                continue

            status, next_action, kind, title = _DECISION_PATCH[decision]
            if (current.fit_score or 0) >= 8:
                if decision == "approve":
                    next_action = "Apply; reach out to people at the company"
                elif decision == "applied":
                    next_action = "Reach out to people at the company"

            before = _input_from_job(current)
            after = before.model_copy(
                update={"status": status, "next_action": next_action}
            )
            changed_fields = [
                key
                for key in ("status", "next_action")
                if getattr(before, key) != getattr(after, key)
            ]
            now = _now()
            activity = _activity(
                JobActivityInput(
                    kind=kind,
                    title=title,
                    detail=(
                        f"{current.company} — {current.role}. "
                        f"Status set to {status}."
                    ),
                    session=session,
                ),
                created_at=now,
            )
            revisions = current.revisions
            if changed_fields:
                revisions = [
                    *revisions,
                    _revision(
                        after,
                        reason=title,
                        changed_fields=changed_fields,
                        created_at=now,
                    ),
                ]
            updated = JobWorkspace(
                **after.model_dump(),
                id=current.id,
                activities=[*current.activities, activity],
                revisions=revisions,
                created_at=current.created_at,
                updated_at=now,
            )
            items[index] = updated.model_dump(mode="json")
            _write_unlocked(items)
            return updated
        return None
```

For fit scores below 8, use `Apply` and `Await response`. For scores 8+, use `Apply; reach out to people at the company` and `Reach out to people at the company`. A repeated command that changes no fields still appends the explicit decision activity but does not add an empty revision.

- [x] **Step 6: Expose the command route and mirror its activity**

In `app/jobs.py`, import `JobDecisionInput` and define a reusable mirror for both input and stored activities (`JobActivity` subclasses `JobActivityInput`):

```python
def _mirror_activity(job_id: str, data: JobActivityInput) -> None:
    if not data.session:
        return
    session_store.append_event(
        SessionEventInput(
            session=data.session,
            kind=data.kind,
            title=data.title,
            detail=data.detail,
            job_id=job_id,
            occurred_at=data.occurred_at or getattr(data, "created_at", None),
            external_id=data.external_id,
        )
    )
```

The decision route calls `_get_job_or_404`, then `job_store.apply_decision`, mirrors `updated.activities[-1]`, and returns the workspace. Return 404 only if the dossier disappeared.

- [x] **Step 7: Run the targeted and complete backend tests**

Run: `uv run pytest tests/test_jobs_api.py -q`

Expected: all jobs API tests pass.

Run: `uv run pytest -q`

Expected: at least 200 tests pass with no failures.

---

### Task 2: Consistent job-person association and activity mirroring

**Files:**
- Modify: `resume-tailor-service/app/people_store.py`
- Modify: `resume-tailor-service/app/jobs.py`
- Modify: `resume-tailor-service/tests/test_jobs_api.py`
- Modify: `resume-tailor-service/tests/test_people_api.py`

**Interfaces:**
- Consumes: `Person`, job `id`, `company`, and `role`.
- Produces: `people_store.person_matches_job(person, job_id, company, role) -> bool`.
- Produces: identical membership semantics for nested job people and `JobSummary.person_count`.

- [x] **Step 1: Write a failing association-consistency test**

Create two Acme jobs with different roles. Add one legacy Acme contact scoped to the first role, one company-wide Acme contact with no role, and one person pinned to the second job. Assert the first summary counts the two matching legacy contacts, the second counts the company-wide plus pinned contact, and each nested people route returns exactly the same set represented by its count.

- [x] **Step 2: Run the association test and confirm the summary mismatch**

Run: `uv run pytest tests/test_jobs_api.py -k people_association -q`

Expected before implementation: FAIL because summary counts currently include every company-level contact regardless of role.

- [x] **Step 3: Implement one shared matcher**

Add this responsibility to `people_store.py`:

```python
def person_matches_job(person: Person, job_id: str, company: str, role: str = "") -> bool:
    if person.job_id:
        return person.job_id == job_id
    if person.company.strip().lower() != company.strip().lower():
        return False
    return not person.role or person.role.strip().lower() == role.strip().lower()
```

Use it in `people_for_job`. In `jobs.list_jobs`, load people once and compute each `person_count` with the same matcher; do not re-read `people.json` once per job.

- [x] **Step 4: Make job-person creation use the shared activity bridge**

Extract an internal helper in `app/jobs.py` that reuses Task 1's `_mirror_activity`:

```python
def _append_job_activity(job_id: str, data: JobActivityInput) -> JobWorkspace | None:
    updated = job_store.add_activity(job_id, data)
    if updated is not None:
        _mirror_activity(job_id, data)
    return updated
```

Use it from both `POST /api/jobs/{job_id}/activity` and nested job-person creation. Reuse a single `JobActivityInput` value so the dossier and session log receive identical kind, title, detail, session, occurred time, and external ID.

- [x] **Step 5: Test people creation in both stores**

Extend `test_job_people_are_pinned_counted_and_logged` to assert the session JSONL contains the `Added Alex Recruiter to reach` event with the created job ID. Keep the existing people API test proving `job_id` round-trips and filters.

- [x] **Step 6: Run focused tests**

Run: `uv run pytest tests/test_jobs_api.py tests/test_people_api.py -q`

Expected: all focused tests pass without writing to the real `data/` directory.

---

### Task 3: Session-log input and read hardening

**Files:**
- Modify: `resume-tailor-service/app/models.py`
- Modify: `resume-tailor-service/app/session_store.py`
- Modify: `resume-tailor-service/tests/test_sessions_api.py`

**Interfaces:**
- Consumes: `SessionEventInput` from direct and mirrored events.
- Produces: stripped `job_id`, normalized optional `external_id`, lock-consistent reads, malformed-line tolerance, and stable last-N filtering.

- [x] **Step 1: Write failing normalization and resilience tests**

Post an event with `job_id=" abc123 "` and `external_id=" action-1 "`, then retry with the trimmed external ID and assert both calls return the same event ID. Seed the JSONL file with one malformed line between two valid events and assert both valid events remain listable. Assert `limit=1` returns only the newest valid event.

- [x] **Step 2: Run the session tests and observe duplicate/whitespace behavior**

Run: `uv run pytest tests/test_sessions_api.py -q`

Expected before implementation: the whitespace-normalization assertion fails.

- [x] **Step 3: Normalize optional identifiers in Pydantic**

In `SessionEventInput`, strip `job_id`; strip `external_id` and convert an empty result to `None`. Keep blank `session`, `kind`, and `title` invalid.

- [x] **Step 4: Serialize reads with appends**

Wrap `list_events` and `list_sessions` reads in `_LOCK`. Keep `_read_all` lock-agnostic so `append_event`, which already holds the `RLock`, can call it without a second filesystem abstraction.

- [x] **Step 5: Run session and full backend verification**

Run: `uv run pytest tests/test_sessions_api.py tests/test_jobs_api.py -q`

Expected: all focused tests pass.

Run: `uv run pytest -q`

Expected: the full suite passes with the new tests included.

---

### Task 4: Dashboard command integration and action-state polish

**Files:**
- Modify: `resume-tailor-service/dashboard/src/api.ts`
- Modify: `resume-tailor-service/dashboard/src/components/Inbox.tsx`

**Interfaces:**
- Consumes: `POST /api/jobs/{job_id}/decision` with `{ decision, session }`.
- Produces: `decideJob(jobId: string, decision: JobDecision, session?: string) -> Promise<JobWorkspace>`.

- [x] **Step 1: Replace stale full-record writes with the decision command**

Remove `DECISION_PATCH` and the client-side `JobWorkspaceInput` reconstruction from `decideJob`. Implement one `jsonRequest` call:

```typescript
export function decideJob(
  jobId: string,
  decision: JobDecision,
  session = "Inbox"
): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(jobId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, session }),
    },
    "Failed to save the inbox decision."
  );
}
```

Update `Inbox.tsx` to call `decideJob(ticket.id, decision)`.

- [x] **Step 2: Show only valid next-step actions**

In `TicketDetail`, compute `canApprove` for `discovered`/`researching` and `canMarkApplied` for `ready`/`applying`. Render Approve and Hold only while a decision is pending; render Mark applied only after approval. Applied/outreach/interview/offer tickets remain readable and keep listing/dossier links without mutation buttons.

- [x] **Step 3: Include all summary search fields**

Extend Inbox search to include `work_mode` and `notes`, matching the backend summary contract already sent to the client.

- [x] **Step 4: Run TypeScript verification**

Run: `npm run typecheck`

Expected: `tsc --noEmit` exits 0.

- [x] **Step 5: Build production assets**

Run: `npm run build`

Expected: TypeScript and Vite finish successfully; `app/static/index.html`, `launch.html`, and hashed JS/CSS assets are regenerated.

---

### Task 5: Operational documentation and backup coverage

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `resume-tailor-service/README.md`
- Verify: `resume-tailor-service/scripts/backup-job-data.sh`
- Preserve: `docs/BROWSER_PROFILE.md`, `scripts/start-job-chrome.sh`, and their concurrent references.

**Interfaces:**
- Consumes: the final API, persistence, and dashboard behavior.
- Produces: one consistent operator story for Inbox, Dossiers, People, sessions, static builds, and backups.

- [x] **Step 1: Update user-facing run instructions**

Change the root and service READMEs so `http://127.0.0.1:8420/` opens Inbox by default, Dossiers remains the full record editor, job-specific people appear inside both views, and session events are available through `/api/sessions*`.

- [x] **Step 2: Update the agent contract without disturbing browser-profile edits**

In the local-dashboard section of `CLAUDE.md`, state that Inbox is the decision queue and Dossiers is the canonical detailed workspace. Preserve the newly added isolated-browser section byte-for-byte.

- [x] **Step 3: Refresh architecture facts**

Update the architecture diagram/store list, router/module map, persistence section, test count, dashboard description, and open CI gap. Do not claim the queue/verifier gaps are fixed.

- [x] **Step 4: Validate the backup script**

Run: `bash -n scripts/backup-job-data.sh` from `resume-tailor-service/`.

Expected: exit 0. Document that the script copies the whole `data/` directory, including `sessions.jsonl`, plus `output/` when present.

- [x] **Step 5: Check documentation links and placeholders**

Run: `rg -n 'T[B]D|T[O]DO|F[I]XME|Dossiers.*default|mounts 3 routers|data/people.json\)' README.md CLAUDE.md docs/ARCHITECTURE.md resume-tailor-service/README.md docs/superpowers/specs/2026-08-27-inbox-session-integration-design.md`

Expected: no stale default-view/router claims and no implementation placeholders in the new spec.

---

### Task 6: End-to-end verification and diff review

**Files:**
- Verify: all files in the approved scope.
- Do not modify: unrelated browser-profile automation unless a verification command proves it is broken.

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: reproducible evidence that backend, dashboard, static serving, and documentation agree.

- [x] **Step 1: Run the complete automated verification matrix**

Run from `resume-tailor-service/`:

```bash
uv run pytest -q
```

Run from `resume-tailor-service/dashboard/`:

```bash
npm run typecheck
npm run build
```

Run from the repository root:

```bash
git diff --check
bash -n resume-tailor-service/scripts/backup-job-data.sh
```

Every command must exit 0; record the exact pytest total and generated asset names.

- [x] **Step 2: Start an isolated local smoke-test server**

Run `uv run uvicorn app.main:app --host 127.0.0.1 --port 8421` from `resume-tailor-service/`. Use port 8421 so the launchd-managed service on 8420 is not interrupted.

- [x] **Step 3: Verify HTTP contracts without mutating personal data**

GET `/health`, `/`, `/launch.html`, `/api/jobs`, and `/api/sessions` on port 8421. Expect 200 for each, `{"status":"ok"}` from health, HTML from the two pages, and JSON arrays from both API lists. Do not click mutation controls against the personal store.

- [x] **Step 4: Perform a visual Inbox smoke test**

Use the in-app browser to confirm the Inbox navigation is selected, ticket list and detail panes render, queue/search controls are usable, the page has no visible runtime error, and Dossiers navigation still opens. Capture a screenshot for review.

- [x] **Step 5: Review the final diff and ownership boundaries**

Run `git status --short`, `git diff --stat`, and focused diffs for every touched implementation file. Confirm no data files, browser-profile files, secrets, or unrelated user edits were added or removed.

- [x] **Step 6: Apply the verification-before-completion workflow**

Re-run any command whose evidence became stale after the last edit. Report only outcomes supported by the final command output; leave the dirty worktree uncommitted for the user.
