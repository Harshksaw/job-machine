# Job Machine: canonical agent brief

**Every agent working in this repo reads this file first.** Claude Code, Cursor, and any
other assistant. The tool-specific files (`CLAUDE.md`, `.cursor/rules/job-machine.mdc`)
are thin pointers to this one and hold no rules of their own.

This repo runs Harsh Saw's job search: discover listings, score fit, build an
evidence-backed application kit, apply, mine people, log everything. The service is a
single FastAPI app on `http://127.0.0.1:8420/` (dashboard + tailor + jobs API). For how
it is built, read `docs/ARCHITECTURE.md`.

---

## Where each fact lives

One file owns each kind of fact. Never restate a fact from another file; link to it. If
two files disagree, the owning file below wins.

| You need | Read | Public? |
|---|---|---|
| Hard rules, eligibility, dossier + sheet contracts | this file (`AGENTS.md`) | yes, committed |
| Claude Code specifics: private memory dir, headless `claude -p` flags | `CLAUDE.md` | yes, committed |
| Harsh's roles, bullets, skills, education, projects, and targeting preferences (`profile_facts`) | `resume-tailor-service/content/resume_bank.yaml` | yes, committed |
| Personal answers: address, salary numbers, exact work status, DOB, French, start date | `docs/PERSONAL-ANSWERS.md` | **no, gitignored** |
| Operating techniques, ATS JD fetches, per-site gotchas, known-broken lanes | `docs/AGENT-PLAYBOOK.md` | yes, committed |
| Dashboard (system of record: Inbox + dossiers) | `http://127.0.0.1:8420/` | local only |
| Live queue state: applied, blocked, in flight | newest `SESSION-HANDOFF-*.md` (current: `SESSION-HANDOFF-2026-08-28.md`) | **no, gitignored** |
| Browser profile setup and CDP wiring | `docs/BROWSER_PROFILE.md` | yes, committed |
| Service internals, endpoints, persistence | `docs/ARCHITECTURE.md`, `resume-tailor-service/README.md` | yes, committed |

**The resume bank is the only description of Harsh's experience.** This file deliberately
does not summarize his work history, stack, or accomplishments. A prose copy here would
drift from the bank, and the bank is what the kit generator validates every claim
against. Read `resume_bank.yaml` when you need to know what he has actually done.

**Contact and links** (the bank's `contact` block is authoritative):
mister.harshkumar@gmail.com | +1 (778) 583-2260 | linkedin.com/in/harsh-kumar-s-32727b247 |
github.com/Harshksaw | harshsaw.me. Resume to upload: `./resume.pdf`, as-is, for every
upload field.

**The `origin` remote is PUBLIC** (github.com/Harshksaw/job-machine). Never commit
`docs/PERSONAL-ANSWERS.md` or `SESSION-HANDOFF-*.md`; both are gitignored. Never paste a
street address, DOB, salary figure, or ATS confirmation code into a committed file.

---

## Hard rules

1. NEVER fabricate experience, skills, dates, or numbers. Every claim traces to
   `resume-tailor-service/content/resume_bank.yaml`.
2. Fit score 1-10 before any apply. Below 6 = retain for review: keep the dossier active,
   save the reason/gaps, and never mark it skipped or archive it automatically. Harsh may
   improve or reconsider it later. 8+ = people-mining eligible.
3. LinkedIn: human pace only. Max 12 connection requests per session. Every outreach
   message shown to Harsh for approval BEFORE sending. No exceptions. Message content
   depends on who they are: **only a recruiter, talent, or HR contact is told which role
   he applied to.** An engineer, founder, hiring manager, or anyone else never hears about
   the application and is never asked for a referral: open with their hook, ask one real
   question about the problem the company is working on, and tie it to one real thing of
   his that aligns with it. Keep both sides general ("building AI systems", "search and
   retrieval"): **no tech stack in an outreach message**, no languages, frameworks,
   databases, or model names, unless it is one genuinely impactful detail verified from
   their own writing that he has real matching work for. Ambiguous title = treat as
   non-recruiter. No em-dashes in any of it. The full recipe is step 2 of
   `prompts/outreach-run.md`.
4. Wellfound note field, which is part of the application itself, so naming the role is
   fine here = custom per company: their product/mission hook, then one relevant real
   project of his, then a genuine close. 3-4 sentences. No "I'm passionate about." Same
   generality rule as rule 3: describe his work as the kind of system it is, not a stack
   list, and no em-dashes.
5. Pause and ask Harsh only for: any dossier answer marked `needs_user_input`, ambiguous
   sponsorship wording, unusual questions the validated answer flow cannot resolve,
   salary questions, or anything requiring a judgment call about him. **A cover letter is
   never on this list.** The generated cover letter goes into the form without review, so
   do not stop to show it or ask. A tailored resume is the one document he must see before
   it is sent.
6. One-line summary per company as you go. Otherwise do not ask permission between
   listings.
7. Never leave a browser action only in chat. The dossier event must be written before
   moving to the next listing. Sheet logging is additionally required after submissions,
   outreach, replies, interviews, and rejections.
8. Never re-send an application. Before every submit, check the dossier store for the same
   company+role already at `applied` and stop if one exists. This is a hard gate, not a
   printed warning. See the dedupe section of `docs/AGENT-PLAYBOOK.md` for how to match.

**How rule 5 interacts with not blocking:** "pause and ask" means queue it visibly and
keep working on everything else, not halt the session. Put the exact question or draft in
an "awaiting your approval" list and move to the next listing. The one true hard stop is
rule 3: an outreach message does not go out before Harsh says yes.

---

## Discovery sources

Search and apply via **LinkedIn, Wellfound, and company ATS boards only**. ZipRecruiter is
also standing, but live-browser only (see the playbook).

There is **no** RDS `job_registry`, **no** `jobs-pipeline/` directory, and **no** local
Postgres jobs mirror. Do not start Docker for a jobs DB, do not look for `RDS_DSN`, and do
not treat "RDS discovery lane is down" in old session notes as a current task. Existing
dossiers with `source: job_registry (RDS)` stay as historical records.

## Eligibility and screening policy

Numbers and personal specifics live in `docs/PERSONAL-ANSWERS.md`. The policy is here:

- **Canada:** authorized to work, no sponsorship needed. "Legally authorized to work" =
  Yes. "Require sponsorship now or in future" = No.
- **US roles:** apply if they sponsor **or are silent** on sponsorship. Answer honestly:
  authorized in the US without sponsorship = No, require sponsorship = Yes. He is
  Canadian and TN-eligible for engineering roles, so note TN in any free text. **Skip**
  only when the listing explicitly says no sponsorship, US citizens or green card only, or
  must already be authorized.
- **Relocation:** US and Canada only. On-site elsewhere (Europe, UK, Central Asia) = skip.
  For on-site North America, "willing to relocate" = Yes, but "are you currently located
  in <city>" = No.
- **Availability:** final-year student, grad Dec 2026, currently interning. Not available
  for immediate, all-in, drop-everything roles.
- **Demographic and self-ID questions:** voluntary, leave blank. Do not answer on his
  behalf.
- Anything not covered here and not in `docs/PERSONAL-ANSWERS.md` is a rule 5 pause.

---

## Job dossiers (MANDATORY every search/apply session)

The dashboard at `http://127.0.0.1:8420/` is the detailed system of record. It opens on
**Inbox**, the decision queue. **Dossiers** is the full record editor. Google Sheets is the
compact pipeline log, not the record.

At the first touch of EVERY listing, including low-fit results, upsert its dossier and keep
the returned `id` for the rest of that listing. `capture` upserts on `job_url`, so reuse
the exact same URL per role or you create duplicates. Status must be one of:
`discovered`, `researching`, `ready`, `applying`, `applied`, `outreach`, `interview`,
`offer`, `rejected`, `skipped`, `archived`.

```
POST http://127.0.0.1:8420/api/jobs/capture
Content-Type: application/json
{
  "company": "...",
  "role": "...",
  "job_url": "...",
  "source": "LinkedIn",
  "location": "...",
  "work_mode": "...",
  "status": "discovered",
  "fit_score": 1,
  "jd_text": "<complete listing text>",
  "company_context": "<specific product/company research>",
  "notes": "<brief decision context>",
  "next_action": "...",
  "session": "<source> <YYYY-MM-DD>"
}
```

After EVERY meaningful action or decision, append a dossier event:

```
POST http://127.0.0.1:8420/api/jobs/<id>/activity
Content-Type: application/json
{
  "kind": "research|decision|applied|outreach|reply|interview|note",
  "title": "<short exact event>",
  "detail": "<what happened, answer submitted, confirmation, or reason>",
  "session": "<source> <YYYY-MM-DD>",
  "occurred_at": null,
  "external_id": null
}
```

For every application, build the evidence-backed kit first:
`POST /api/jobs/<id>/generate-kit?session=<session>`. Use its cover letter when the form
asks for one, with no approval step: it is already evidence-backed, so paste it and move
on. For an unusual question, call `POST /api/jobs/<id>/answers/generate` with
`{question,constraints,session}` and check the saved answer before using it. The endpoint
intentionally returns `needs_user_input=true` for salary, sponsorship/authorization,
start-date, and other unknown personal judgments. **Never bypass that flag.**

**Resume:** upload the original `./resume.pdf` as-is. Do not tailor unless a role really
requires it. If you do tailor, **show Harsh the actual tailored resume before it is sent**
and wait for his yes. He approves the document itself, not the idea of tailoring, so print
what changed against the original. This is the only artifact gated this way.
Include `job_id`, `job_url`, and `session` in the `POST /tailor` body so the PDF
attaches to the dossier and the artifact is logged. Details in `docs/AGENT-PLAYBOOK.md`.

## Sheet logging (MANDATORY after external actions)

Open as a URL in the browser, URL-encode values, and confirm `{"ok":true}` in the
response. `curl` hits a Google sign-in wall, so it must go through the browser's Google
session.

```
https://script.google.com/macros/s/AKfycbz4hpb7VnQIsHEiOyN6wa-7R254QOdo3n0QK-pNw7gJ52a3BbKltIx0pY1PqYkfD2SJLA/exec?company=&role=&source=&jobUrl=&status=&fit=&people=&hooks=&outreach=&notes=
```

Statuses: `applied` | `people-mined` | `outreach-sent` | `outreach-queued` | `replied` |
`interview` | `rejected`

---

## Automation browser

Default is the isolated job Chrome: `./scripts/start-job-chrome.sh` writes to
`./browser-profile/` and exposes CDP on **9222 by default**
(`JOB_MACHINE_CDP_PORT` overrides it), then `export BU_CDP_URL=http://127.0.0.1:9222`.
Recent sessions have run on **9223**, so confirm the live port with
`curl -fsS http://127.0.0.1:<port>/json/version` instead of assuming. Full setup:
`docs/BROWSER_PROFILE.md`.

When Harsh says use his **standard/regular Chrome profile**, use
`./scripts/start-chrome-debug.sh` (default profile, no `--user-data-dir`; he must Cmd+Q
Chrome first).

**Only one process may drive `browser-profile/` at a time.** Check with
`ps aux | grep [c]laude` and `ps aux | grep [p]laywright-mcp` before starting. Concurrent
writers have corrupted dossier status and fired unintended LinkedIn invites. See the
playbook.

## Working style

- **No em-dashes anywhere**, in messages, outreach notes, or drafts. Use commas, periods,
  or colons. Prefer plain "to" or "->" over arrows.
- **Never flag or hold back on spend.** Harsh's standing directive: optimize for outcomes
  and coverage, not token cost. Do not suggest a fresh session to reset cost.
- Be lean for speed, not for budget: batch independent tool calls, prefer text extraction
  over screenshot loops, do not re-verify what a tool already confirmed.
- Session scratch (screenshots, UI snapshots) goes in `session-artifacts/<session>/`,
  which is gitignored, never the project root.
- Fill forms from stored data rather than an LLM per field. Write a custom answer only
  when the form genuinely needs a cover letter or "why you" essay: short, truthful,
  sourced from the resume bank.
