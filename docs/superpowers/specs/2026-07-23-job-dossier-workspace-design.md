# Job Dossier Workspace - Architecture and Operating Model

Date: 2026-07-23
Status: Implemented

## Problem found in the existing setup

The repository had four useful pieces:

1. Browser-run prompts for LinkedIn, Wellfound, and outreach.
2. A fact-locked resume bank and one-page PDF tailoring service.
3. A Google-Sheet application pipeline rendered as a table/board.
4. A local People/outreach store.

Each piece worked, but the job itself was not a durable first-class record.
The full JD lived only in a generated resume directory, fit reasoning was a
single number or note, Sheet rows represented actions rather than one listing,
people were joined only by company text, and cover letters/form answers had no
home. A session could therefore be summarized, but not reliably reconstructed.

## Operating model

`data/jobs.json` is the detailed local source of truth. Google Sheets remains a
small external milestone log and import source. `data/people.json` remains the
contact store. `output/<resume-id>/` remains the immutable PDF artifact store.

```text
Browser or manual entry
  -> POST /api/jobs/capture
  -> one JobWorkspace per listing
       |- complete JD + research
       |- validated fit analysis and source ledger
       |- editable cover letter and form answers
       |- tailored_resume_id -> output/<id>
       |- company/role -> People records
       |- append-only activity ledger
       `- restorable full snapshots

Google Sheet rows
  -> POST /api/jobs/import-sheet
  -> upsert by exact job URL, then normalized company+role
  -> deduplicated activity events
```

## Dossier data

Core listing fields:

- company, role, URL, source, location, work mode, compensation
- workflow status, priority, fit score, deadline, next action
- complete job description, company context, reason for interest, notes

Curated application fields:

- `FitAnalysis`: score, apply/review decision, verdict, role thesis, exact JD
  keywords, requirement-by-requirement evidence, honest gaps, positioning
- `FitEvidence`: requirement, strong/partial/gap, proof, resume-bank source IDs
- editable cover letter
- `ApplicationAnswer`: question, constraints, answer, state, source IDs, and a
  `needs_user_input` guard
- tailored resume ID

Traceability fields:

- activity with kind, title, detail, session, event time, and optional external
  deduplication ID
- revision with reason, changed fields, timestamp, and a complete restorable
  `JobWorkspaceInput` snapshot

## Generation and fidelity

Application-kit and answer generation use the existing authenticated Claude
CLI wrapper. The model receives a source ledger built from the resume bank:

- every experience/project/achievement bullet ID
- stable IDs for selectable/reorderable skill categories
- verified education, location, experience-level, target-role, relocation, work
  mode, and company-stage preference entries

Validation rejects:

- unknown source IDs
- score/recommendation conflicts (`<6 = review`, `>=6 = apply`); low-fit
  dossiers stay active with editable artifacts and are never skipped
  automatically
- keywords absent from the JD
- evidence without sources (unless explicitly a gap)
- untraceable named, technical, acronym, or numeric facts
- cover-letter placeholders and common generic opening phrases

Salary, compensation, authorization/sponsorship, visa, start-date, demographic,
and similar personal questions are detected before any model call and stored as
requiring user input.

Residual: as with the original resume summary validator, lowercase qualitative
phrases without named/numeric facts are prompt-constrained rather than fully
machine-provable. Generated text is therefore a reviewed draft, while cited
candidate evidence remains structurally verifiable.

## Page workflow

The default Dossiers view is a dense two-pane operational surface:

- searchable/status-filtered listing rail
- editable header, fit, status, and priority
- Overview: analysis matrix, listing metadata, research, JD, and linked people
- Resume: exact selected evidence beside the rendered one-page PDF
- Letter: editable letter plus claim ledger
- Answers: manual or validated drafts with approval/submission state
- Activity: session ledger, JSON export, revision snapshots, restore action

The existing Pipeline, Board, Inspector, and People views remain available.
Pipeline rows can create/open their matching dossier. Dossier loading is local
and independent of Sheet availability.

## Boundaries

- Single user, local only, no authentication; bind to `127.0.0.1`.
- JSON plus atomic replace is appropriate at current volume. Move jobs, people,
  revisions, and events to SQLite before concurrent writers or multi-user use.
- Browser automation still performs external search and submission. The run
  prompts now require a capture/event call so those actions appear in the page.
- Sending outreach still requires explicit user approval.
