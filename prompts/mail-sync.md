# Mail sync run

Goal: every rejection, interview invite, assessment and recruiter reply in Harsh's inbox
ends up on the right dossier. Read `AGENTS.md` first. This run reads mail and writes
dossier events. It never sends, labels, archives or deletes mail.

**The service now does this itself (orchestrator M8).** Once Harsh has a Gmail token
(`docs/MCP-AND-MAIL-SYNC.md`), run `cd resume-tailor-service && uv run python
scripts/run_task.py mail_sync` (or queue `mail_sync` with the `enqueue_run` MCP tool).
It runs steps 1 to 4 below in code, with only the classification on a model, and keys
every write on the Gmail message id, so it never double writes with this manual lane.
Then do step 5 from its report (`GET /api/pipeline/mail/status`): `waiting_on_harsh`,
`interviews`, `held` (open those threads), `unmatched`, and log every `sheet_log` entry
to the Sheet through the browser, since the Sheet needs the browser's Google session.

Use the manual lane below only while there is no token. It needs an agent with Gmail
access (Claude Code has the Gmail connector).

## 1. Find the window

The last run's events file is the newest `session-artifacts/mail-sync-*/events.json`.
Search from two days before its newest `date`, so nothing at the boundary is missed.
Reruns are safe: the script keys every write on the Gmail message id.

## 2. Search

Run these as Gmail queries with `after:<date>` and `-in:sent`, summary view:

- Outcomes: `"unfortunately" OR "not to move forward" OR "other candidates" OR "decided not to" OR "position has been filled" OR subject:interview OR "schedule an interview" OR "was accepted" OR "assessment" OR "next step"`
- ATS senders, to catch wording the first query misses:
  `from:(ashbyhq.com OR greenhouse-mail.io OR hire.lever.co OR myworkday.com OR ats.rippling.com OR remail.wellfound.com OR workatastartup@ycombinator.com) -subject:("thank you for applying" OR "application received")`

Skip receipts ("thank you for applying", "we received your application"), security codes,
newsletters, and anything that is not about a job application.

## 3. Classify

One event per email:

```json
{"id": "<gmail message id>", "company": "Acme", "role": "Software Engineer",
 "date": "2026-01-31", "outcome": "rejected", "confident": true, "note": "one line"}
```

- `outcome`: `rejected` (includes "role filled"), `interview` (a person will talk to
  him), `assessment` (test, take home, one way video), `reply` (a human wrote, no
  decision yet).
- `confident: false` when the snippet is cut off before the decision. Then open the
  thread and read it. A body phrase search is not proof: receipts also say "if you are
  not selected".
- `company` is the employer, not the ATS or the board. Rippling mail for "B-Yond" is the
  Reailize dossier.

Save the list to `session-artifacts/mail-sync-<YYYY-MM-DD>/events.json`.

## 4. Write

```
cd resume-tailor-service
uv run python scripts/mail_outcomes.py ../session-artifacts/mail-sync-<date>/events.json          # dry run
uv run python scripts/mail_outcomes.py ../session-artifacts/mail-sync-<date>/events.json --apply
```

Read the dry run before applying. `UNMATCHED (ambiguous: ...)` means the company has
several applied dossiers: open the thread, find the exact role, set `role` to the
dossier's title and rerun. `UNMATCHED (no dossier)` is an application made outside the
machine: list those for Harsh, do not create dossiers for them.

## 5. Report

Tell Harsh, in this order: anything waiting on him with a deadline (assessments, video
interviews, scheduling links), new interviews, then counts of rejections written, held
and unmatched. Log interviews and rejections to the Sheet per `AGENTS.md`.
