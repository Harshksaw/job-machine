# Outreach session (Wednesdays, send cap in AGENTS.md rule 3)

Read `AGENTS.md` first (hard rules, dossier + sheet contracts). Then
`docs/AGENT-PLAYBOOK.md` for LinkedIn connect-with-note selectors and the 300-char
note cap. Use playwright mcp. This session sends nothing without approval
(`AGENTS.md` rule 3).

1. Open `http://127.0.0.1:8420/` -> Dossiers + People (or read
   `GET /api/jobs` and `GET /api/people`). Build the queue from active dossiers
   with fit ≥ 8 and people in `to-reach`/`queued`, newest first. Use the Sheet
   only as a compatibility cross-check. Set session=`Outreach <YYYY-MM-DD>`.
2. For each person (cap the send list per `AGENTS.md` rule 3): draft a LinkedIn
   connection note, ≤ 300 chars. Branch on their title:
   - **Recruiter / talent / HR / people ops:** open with THEIR hook (specific,
     from the hooks column), then one line of my relevance, a real project and
     real number from `resume-tailor-service/content/resume_bank.yaml` that
     matches what their company builds, then name the role I applied to.
   - **Engineer / founder / hiring manager / anyone else:** NEVER mention the
     application, never ask for a referral or a job. Open with THEIR hook, then
     ask one genuine question about the problem the company is working on, kept
     at the product level: what they are building and why, the hard part of it,
     where it is heading. Tie it to the one real thing of mine that aligns,
     described in the same general terms ("building AI systems", "search and
     retrieval", "shipping product end to end"), not as a feature list. End on
     the question.
   - **No tech stack in the message.** Do not name languages, frameworks,
     databases, or model names on either side. The exception is a single
     genuinely impactful detail I actually verified from their post or their
     engineering writing, and that I have real matching work for. Absent that,
     stay generic.
   - **Never mention that I am a student, a new grad, graduating, or looking.**
     No "final-year", no "about to graduate", no "breaking into", no "recent
     grad reaching out". Status is not the story and it reframes everything
     after it as a favour request. I am someone who builds things, writing to
     someone who builds things. Present tense, what I am working on now.
   - **The message is about the work and the question, not about me.** Roughly:
     their hook, the question, one line of mine that earns the question. If a
     sentence is about my situation rather than the work, cut it.
   - **Both:** no em-dashes, ever (`AGENTS.md` working style). No flattery
     filler, no "passionate", no "I'd love to", no "just wanted to reach out",
     no compliment openers. Read like one engineer to another.
   - If the title is ambiguous, treat them as non-recruiter and ask the
     question. Only an explicit recruiting/talent/HR title unlocks the
     applied-to-role line.
3. Show ALL drafts in one batch: person | company | draft. Wait for approval/edits.
4. After approval: save the approved text on the Person record, then send each
   request at human pace (30-60s apart, browse the profile briefly first). Use the
   job profile on CDP 9223 with `new_tab(profile_url)` per send (background tab,
   close only that tab after verify). Regular Chrome cannot serve CDP on Chrome
   136+, see `AGENTS.md`. Tab etiquette: `docs/AGENT-PLAYBOOK.md` "Outreach send
   workflow" and "Regular Chrome: do not disturb existing tabs".
   Update the Person to `sent`; append an `outreach` activity with the exact
   message to the matching dossier; then log status=outreach-sent using the
   webhook in `AGENTS.md`.
5. Follow-ups: use dossier activity timestamps to find outreach sent 5+ days
   ago without a reply: draft a follow-up message (give-not-ask: a genuine
   technical question about their stack or a comment on something new they
   shipped; NEVER "just following up"). Same approval batch, same logging.
6. Anyone beyond the send cap: update Person=`queued`, append a dossier activity,
   and log status=outreach-queued using the webhook in `AGENTS.md` for next week.
7. End: summary of sent, queued, follow-ups, dossier-event count, Sheet-row
   count, and anything that looked like a reply in my LinkedIn inbox (list it,
   don't respond).
