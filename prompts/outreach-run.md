# Outreach session (Wednesdays — send cap in AGENTS.md rule 3)

Read `AGENTS.md` first (hard rules, dossier + sheet contracts). Then
`docs/AGENT-PLAYBOOK.md` for LinkedIn connect-with-note selectors and the 300-char
note cap. Use playwright mcp. This session sends nothing without approval
(`AGENTS.md` rule 3).

1. Open `http://127.0.0.1:8420/` → Dossiers + People (or read
   `GET /api/jobs` and `GET /api/people`). Build the queue from active dossiers
   with fit ≥ 8 and people in `to-reach`/`queued`, newest first. Use the Sheet
   only as a compatibility cross-check. Set session=`Outreach <YYYY-MM-DD>`.
2. For each person (cap the send list per `AGENTS.md` rule 3): draft a LinkedIn
   connection note, ≤ 300 chars:
   - open with THEIR hook (specific, from the hooks column)
   - one line of my relevance: a real project + real number from
     `resume-tailor-service/content/resume_bank.yaml` that matches what their
     company builds
   - mention the role I applied to
   - no flattery filler, no "passionate", read like one engineer to another
3. Show ALL drafts in one batch: person | company | draft. Wait for approval/edits.
4. After approval: save the approved text on the Person record, then send each
   request at human pace (30-60s apart, browse the profile briefly first).
   Update the Person to `sent`; append an `outreach` activity with the exact
   message to the matching dossier; then log status=outreach-sent using the
   webhook in `AGENTS.md`.
5. Follow-ups: use dossier activity timestamps to find outreach sent 5+ days
   ago without a reply — draft a follow-up message (give-not-ask: a genuine
   technical question about their stack or a comment on something new they
   shipped; NEVER "just following up"). Same approval batch, same logging.
6. Anyone beyond the send cap: update Person=`queued`, append a dossier activity,
   and log status=outreach-queued using the webhook in `AGENTS.md` for next week.
7. End: summary — sent, queued, follow-ups, dossier-event count, Sheet-row
   count, and anything that looked like a reply in my LinkedIn inbox (list it,
   don't respond).
