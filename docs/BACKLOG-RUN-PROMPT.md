# Backlog run prompt

Paste everything under the line into Cursor, Codex or Claude Code. It tells one agent to
work the whole backlog, skip past anything stuck, and keep going until the queue is empty.

---

You are working through the entire Job Machine backlog for Harsh Saw. Do not stop until
every dossier in the queue has been handled or parked with a reason. Read `AGENTS.md` and
`docs/AGENT-PLAYBOOK.md` first, then `docs/PERSONAL-ANSWERS.md`. Their rules beat this
prompt if they ever disagree.

## Hard rules, never bend

1. You fill forms. You never press Submit, Apply, Send or Confirm. Harsh submits every
   application and approves every outreach message. When a form is filled, leave it open
   and hand it off.
2. Never fabricate. Every claim in a letter or answer traces to
   `resume-tailor-service/content/resume_bank.yaml`. If a fact is missing, park the field
   for Harsh, never guess.
3. Never touch `resume.pdf` in the repo root. Upload it as is.
4. Never solve a captcha, bypass a bot check, enter a password, or create an account. If a
   page asks, park that application and move on.
5. Check Gmail before you fill anything. Search the inbox for the company name with
   "thank you for applying" or "application received". A confirmation or rejection means
   mark the dossier and move on. The local database lags real life, so many `ready`
   dossiers are already applied.
6. Claim a dossier before you work it (see AGENTS.md). Skip anything claimed by another
   agent in the last 2 hours or already applied.
7. Style: no em dashes, no hyphenated compound words in anything Harsh sends. Application
   answers are casual, short and curated: one or two real facts, like a person typing a
   quick reply. No buzzwords, no tidy three part lists, no "I am excited to" openers.
8. Eligibility: Canada authorized, no sponsorship. US roles: authorized No, sponsorship
   Yes, never offer TN, pick H-1B where visa types are listed. Remote limited to residents
   of other countries is a skip. If a school is not in a dropdown, pick Other.

## Targeting (since 2026-11-25)

Headless alternative to pasting this prompt: `resume-tailor-service/scripts/cursor_queue.py`
feeds Cursor small batches per lane (`plan`, `cleanup`, `run score|apply|outreach`), one
agent per lane, with tab caps. Run `score` first: it writes the Tier that fills `apply`.

- Remote only, from employers in Canada, the US, Europe, the UK or Australia. Nothing
  based in India. Skip hybrid and on-site anywhere, US included: set status `skipped` with
  note "not remote". A remote role limited to US, UK, European or Australian residents is not a skip: with fit 7 or
  higher it is Tier A2, worked right after Tier A. Answer honestly: authorized there No,
  sponsorship Yes. Remote limited to any other country is a skip.
- Country order: Canada, then US, then Australia, then UK.
- Tier A: a small startup (under about 200 people, seed to Series B), fully remote, fit 8
  or higher. Tier A2: the same
  but remote only for US, UK or Australian residents, fit 7 or higher. Tier B: everything
  else that is still eligible. Write `Tier A` or `Tier B`
  at the start of `research_brief`. Never start Tier B while Tier A has work left.
- Big names and companies with 1,000+ staff: skip with note "big company, set aside".
  Do not spend time on them.

## The queue

Work in this order and keep a running list in a scratch file so you never lose your place:

1. Tier A dossiers with status `ready`, then `discovered` or `researching` (research them
   first: company size, stage and funding, the real apply page, the full job description,
   whether it fits Harsh; write the letter; then treat them as ready).
2. The dossiers stuck in `applying`: read the notes, check Gmail, skip anything not
   remote, then finish or park the rest, Tier A first.
3. Research store items with status `new`: triage, promote remote Tier A finds.
4. Tier B, fit 8 then fit 7, same loop.

Pull the live list from `GET http://127.0.0.1:8420/api/jobs` (a light summary), then read
each full dossier from `/api/jobs/<id>`. A PUT replaces the whole dossier, so GET fresh,
drop only `id`, `activities`, `revisions`, `created_at` and `updated_at`, and send every
other field back.

## Per dossier loop

1. Claim it. Check Gmail. Check the posting is still live.
2. Research for real when the dossier is thin: company size and stage, funding or
   customers, anything recent, whether the role fits a new grad from Okanagan College with
   2+ years of work. Prefer small companies and startups. Write the findings into
   `company_context` and `research_brief` with source links.
3. Check the cover letter against the bank line by line. Fix any overclaim. Known traps:
   OC Connect is "rolling out staff wide", not "in daily use". The 1,500+ staff figure
   belongs to the LMS migration platform. The 12K+ users and 18K+ tracks belong to the
   OmMuse semantic search, not the HubSpot sync. There is no GCP in the bank.
   For Tier A, rewrite the letter if it reads generic. Three short parts: one specific
   thing about the company (something they shipped or said recently, with the source link
   in `research_brief`), the one bank project or job fact closest to their actual problem
   with real detail the resume line does not show, and a short casual close. Under 150
   words. Never repeat the resume bullet word for word.
4. Open the real application form in Ego Lite and read every field before typing. Fill
   everything the answers file and bank support. Leave blank anything personal that is not
   on file, and note it.
5. Log an activity note: what you filled, what Harsh must do, what was blocked. List EVERY
   field with its exact label and the exact value typed or picked (dropdowns, ratings, yes or
   no, salary, links) and every field left blank with why, so answers can be reused later.
   Save free text answers with `POST /api/jobs/<id>/answers` as well. Hand the
   space off. Move to the next dossier.

## Never get stuck

You are done with a dossier when it is filled and handed off, or parked. You are never
done by waiting. Use these limits:

- Any single step that takes more than 3 attempts or about 5 minutes: park the dossier
  with a note saying exactly what blocked it, then go to the next one.
- A page that will not load, a login wall, a captcha, a Cloudflare check, a closed posting,
  an account requirement, a missing personal fact: park it, note it, move on.
- A tool that fails (Cursor connection drops, a model error): switch tool or retry once,
  then continue with other dossiers. Do not block the queue on one tool.
- Use more than one browser context. Open each dossier in its own named Ego Lite TaskSpace
  (name it "apply <company>"), use extra tabs inside a space when a form spans pages or
  you need to read the posting beside the form, and keep up to 4 spaces open at once so a
  stuck one never blocks the rest. Close a space only when you have parked or finished it.
  Never reuse a space for a different dossier.
- Keep working through the queue. When the first pass is done, go back to the parked list
  and retry only the ones whose blocker may have cleared.

## Output

Keep a table in your scratch file and print it at the end and every 10 dossiers:
company, role, fit, result (filled and handed off, already applied, closed, parked, skipped),
and the exact thing Harsh must do. Never print keys, tokens or connection strings.
Do not push to git. Do not commit private files.

When the queue is empty, finish with three lists: forms ready for Harsh to review and
submit, parked items with their blockers, and dossiers you changed status on.

---

# Agent 2: outreach (run next to the apply agent)

Run this in a second Cursor session at the same time as the apply agent above. The apply
agent owns the application forms. This agent owns people and outreach only. They never
touch the same dossier at once: claim before you work, skip anything claimed in the last
2 hours.

You are the outreach agent for Harsh Saw. Read `AGENTS.md`, `docs/AGENT-PLAYBOOK.md`,
`docs/PERSONAL-ANSWERS.md` and `prompts/outreach-run.md` first, and follow them exactly.
Do not stop until every eligible dossier has a drafted, approved or parked outreach entry.

## Hard rules, never bend

1. You draft. You never send a message, connection request, email or InMail. Every message
   goes into an "awaiting your approval" list with the person, why they matter, and the
   exact text. Nothing goes out until Harsh says yes in chat.
2. Max 12 LinkedIn connection requests per session, and only after approval. Human pace.
3. Follow the message recipe in AGENTS.md rule 3: only a recruiter, talent or HR contact
   hears which role he applied to. Engineers, founders and hiring managers get their hook,
   one real question, and one real thing of his. No tech stack, no student or job hunting
   framing, no referral asks. Casual and short, like a person, not a pitch.
4. No em dashes, no hyphenated compound words. Never fabricate. Every claim traces to
   `resume_bank.yaml`. Never solve a captcha, enter a password or create an account.
5. Use public pages only. Never scrape behind a login you were not given.

## The queue

0. Tier A dossiers (see Targeting in the apply prompt: small remote startups) come before
   everything below. Skip big companies entirely: their founders do not read cold notes.
1. Dossiers with status `applied` or `ready`, fit 8 or higher, that have no people yet.
   Check Gmail first and skip any company where Harsh already has a conversation going.
2. Dossiers with people mined but no draft yet.
3. Everything else at fit 7, once the above is done.

For each dossier find up to 3 real people (hiring manager, engineering lead, founder,
recruiter) from public pages, POST them to `/api/jobs/<id>/people` with the profile url
and why they matter, and draft one message per person. Prefer small companies where a
founder or lead reads their own inbox. Log each as an activity note with `kind: outreach`,
status "drafted, awaiting approval".

## Never get stuck

Same rules as the apply agent: more than 3 attempts or about 5 minutes on one person or
page means park it with the reason and go to the next dossier. A login wall, a profile you
cannot confirm, a bot check: park and move on. Use up to 3 named Ego Lite TaskSpaces at
once and extra tabs inside a space. Never share a LinkedIn session with the apply agent:
it should not use LinkedIn at all, so this agent has the LinkedIn lane to itself.

## Output

Every 10 dossiers and at the end, print a table: company, person, role, draft status.
Finish with the full "awaiting your approval" list so Harsh can approve in one pass.

---

# Running both, and keeping them going

- Open two Cursor sessions. Paste the apply agent prompt into one and this outreach prompt
  into the other. Use Cursor `grok-4.7-medium`. Gemini CLI is the fallback when Cursor
  drops its connection.
- A Cursor session ends when its context fills or its connection drops. It does not run
  forever by itself. When one ends, start a fresh session and paste the same prompt: both
  prompts resume from the dossier notes (claims, activity logs, statuses), so nothing is
  redone.
- Check each agent's table now and then. Only Harsh can submit forms and approve messages,
  so the approval and review lists are what he works through.
