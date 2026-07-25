# Outreach session (Wednesdays — max 12 connection requests total)

Use playwright mcp. Profile + rules in CLAUDE.md. This session sends nothing
without my approval.

1. Open `http://127.0.0.1:8420/` → Dossiers + People (or read
   `GET /api/jobs` and `GET /api/people`). Build the queue from active dossiers
   with fit ≥ 8 and people in `to-reach`/`queued`, newest first. Use the Sheet
   only as a compatibility cross-check. Set session=`Outreach <YYYY-MM-DD>`.
2. For each person (cap the send list at 12): draft a LinkedIn connection note,
   ≤ 300 chars:
   - open with THEIR hook (specific, from the hooks column)
   - one line of my relevance: a real project + real number from CLAUDE.md that
     matches what their company builds
   - mention the role I applied to
   - no flattery filler, no "passionate", read like one engineer to another
3. Show me ALL drafts in one batch: person | company | draft. Wait for my
   approval/edits.
4. After approval: save the approved text on the Person record, then send each
   request at human pace (30-60s apart, browse the profile briefly first).
   Update the Person to `sent`; append an `outreach` activity with the exact
   message to the matching dossier; then Sheet-log status=outreach-sent,
   people={name}, notes={message}.
5. Follow-ups: use dossier activity timestamps to find outreach sent 5+ days
   ago without a reply — draft a follow-up message (give-not-ask: a genuine
   technical question about their stack or a comment on something new they
   shipped; NEVER "just following up"). Same approval batch, same logging.
6. Anyone beyond the 12-cap: update Person=`queued`, append a dossier activity,
   and Sheet-log status=outreach-queued for next week.
7. End: summary — sent, queued, follow-ups, dossier-event count, Sheet-row
   count, and anything that looked like a reply in my LinkedIn inbox (list it,
   don't respond).
