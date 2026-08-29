# Inbox and Session Integration Design

**Date:** 2026-08-27
**Status:** Approved for implementation

## Context

Job Machine already stores job dossiers, activities, tailored artifacts, and
outreach people in the local FastAPI service. The active working tree adds the
beginnings of a ticket-style Inbox, job-specific people links, and a
cross-dossier session narrative. The change needs to be completed as one
coherent release without replacing the existing dossier store or discarding
the in-progress work.

## Goals

- Make Inbox the dashboard's default operational view.
- Derive actionable queues from the canonical dossier statuses and summary
  fields instead of creating a second job store.
- Support quick approve, hold, and applied decisions while retaining the full
  dossier workspace for detailed edits.
- Associate outreach people with a specific job while preserving legacy
  company-based associations.
- Persist an append-only, queryable session narrative across jobs and browser
  actions.
- Keep existing `jobs.json` and `people.json` records compatible.
- Ship source, tests, committed frontend assets, backup behavior, and system
  documentation together.

## Non-goals

- Major Python, Node, React, Vite, or Tailwind dependency upgrades.
- Building the previously designed SQLite tailoring queue, review console, or
  canonical resume verifier.
- Replacing JSON persistence with a database.
- Adding network authentication; the service remains loopback-only.
- Changing the external job-search and outreach approval rules in `CLAUDE.md`.

## Backend design

### Job summaries and Inbox decisions

`JobSummary` gains the fields needed to render and filter Inbox tickets:
`work_mode`, `notes`, `has_cover_letter`, `needs_user_input`, and
`person_count`. These are computed from the canonical dossier and people
stores, so Inbox never owns separate state.

Inbox decisions use a dedicated
`POST /api/jobs/{job_id}/decision` command. The server maps each action to a
valid dossier transition and, under the dossier-store lock, changes only
`status` and `next_action` while appending the matching activity and revision.
This prevents a stale Inbox detail response from replacing newer dossier
content written by an agent or another dashboard view. Approve and hold are
accepted only from `discovered` or `researching`; applied is accepted only from
`ready` or `applying`. Invalid transitions return HTTP 409 without mutation.

### Job-specific people

`PersonInput` gains an optional `job_id`. New nested routes list and create
people for a dossier. A person with a matching `job_id` belongs to that exact
job; legacy records without a `job_id` continue to match by normalized company
name. Job summary counts use the same association rules.

Creating a person from a job records a dossier research activity. Updating a
person in the embedded UI preserves its existing association, including the
empty `job_id` used by legacy company-level contacts. If the dossier disappears
during nested creation, the new person is removed again before the API returns
404; a failed compensation is reported explicitly.

### Session narrative

Session events are stored in `data/sessions.jsonl`, one validated JSON object
per line. Reads and appends share a process-local re-entrant lock. Reads skip
malformed records and cap the byte window so a damaged or unexpectedly large
log does not prevent the dashboard from loading.

The API exposes:

- `GET /api/sessions` for reverse-chronological session summaries.
- `GET /api/sessions/events` filtered by session and/or job.
- `POST /api/sessions/event` for browser or agent actions not represented by a
  dossier activity.

An `external_id` is idempotent within one session. Explicit activity API calls
and Inbox mutations with a non-empty session are mirrored to the session log.
Direct session events do not write back to a dossier, preventing recursive
duplication. Mirroring is supplementary: if a log write fails after the primary
job or person mutation has persisted, the failure is logged and the API still
returns the successful primary mutation, avoiding duplicate retries.

Identifiers used for job filters are validated before querying. Pydantic
rejects blank session names, event kinds, and titles.

## Dashboard design

Inbox becomes the initial navigation view. It fetches lightweight job
summaries, refreshes them periodically, and exposes five derived queues:

- Needs decision: discovered or researching.
- Approved: ready or applying.
- Applied: applied, outreach, interview, or offer.
- Needs you: active jobs with at least one answer requiring user input.
- All: every non-closed job.

Tickets sort by fit score, then priority, then update time. The detail pane
shows decision controls, evidence and gaps, next action, links, and embedded
job-specific outreach people. A dossier button opens the existing workspace
with that job selected.

The dossier workspace also embeds the same job-people component. The global
People view remains available for cross-job outreach management.

API calls use the existing shared error handling. Mutations show an inline
error and leave the last loaded ticket intact; successful mutations refresh
the summary list and detail record.

## Persistence and operations

`data/sessions.jsonl` remains local and gitignored. The data backup script
copies dossier, people, and session files into a timestamped destination
without modifying the originals. Generated Vite assets under `app/static/`
are rebuilt and committed with their source changes so a clean Python-only
checkout still serves the dashboard.

## Testing

Backend tests cover:

- Session event creation, idempotency, filtering, summaries, and malformed
  log tolerance, including read/write lock coordination.
- Mirroring labeled job activities into session history.
- Atomic Inbox decisions that preserve unrelated dossier fields and reject
  invalid status transitions without mutation.
- Job summary Inbox fields and per-job people counts.
- Job-specific people creation, listing, and legacy company fallback.
- Best-effort activity/session mirroring when a supplementary store is
  unavailable after a primary mutation.
- Compensating nested-person rollback and refusal to overwrite an unreadable or
  malformed people store.
- Existing dossier, people, tailoring, and health behavior through the full
  pytest suite.

Frontend verification covers dependency-free Node tests for association
preservation, TypeScript checking, and a production Vite build. Backend
contract tests cover every summary field and state transition the Inbox
consumes.

## Completion criteria

- All backend tests pass from the service directory.
- Dashboard typecheck and production build pass.
- Committed static asset references resolve to the newly generated files.
- `git diff --check` reports no whitespace errors.
- README and architecture documentation describe Inbox, session persistence,
  job-specific people, backup coverage, and current verification results.
- No pre-existing user changes are reset or overwritten outside this scope.
