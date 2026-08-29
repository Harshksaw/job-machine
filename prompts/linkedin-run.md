# LinkedIn session (target: ~8-10 applications, human pace, ~50 min)

Read `AGENTS.md` first (hard rules, eligibility, dossier + sheet contracts). Then
`docs/AGENT-PLAYBOOK.md` for Easy Apply iframe and connect-selector gotchas, and
`docs/PERSONAL-ANSWERS.md` before filling any form field. Use playwright mcp.
LinkedIn is a networking asset: human pace, natural pauses between actions,
nothing bulk.

Set one session label at the start: `LinkedIn <YYYY-MM-DD>`. Use it on every
dossier capture, artifact request, answer, and activity event.

1. Open linkedin.com/jobs (logged in via persistent profile).
2. Search: "Software Engineer New Grad", "Backend Engineer", "Full Stack Engineer",
   "AI Engineer". Filter: posted past week, then past 24h for a second pass.
   Prioritize Easy Apply + small companies.
3. Per listing: read the complete JD, score fit 1–10, capture the dossier per
   `AGENTS.md`, and keep the returned `id`. Generate the kit (including below-6
   listings, so a draft exists for later review) and any unusual-question answers
   per `AGENTS.md`. Pause on `needs_user_input`.
   - Fit below 6: retain for review per `AGENTS.md` rule 2, then next listing.
   - Fit 6+ Easy Apply: fill with verified facts. Upload `./resume.pdf` as-is
     unless the role truly requires a tailored PDF (confirm with Harsh first;
     see `AGENTS.md`). Use the dossier cover letter when requested. Submit, then
     mark applied and log the sheet row using the webhook in `AGENTS.md`.
   - Fit 6+ external-redirect: if the external form is quick (Lever/Ashby style),
     complete it; if it's a Workday/Greenhouse marathon, set dossier
     `status=applying`, `next_action=Complete portal application`, append a
     `decision` activity, log status=outreach-queued and notes=portal-queue
     using the webhook in `AGENTS.md`, then move on.
4. Small startups (<50 people) with fit ≥ 8: open company page → People tab.
   Capture founders / founding-senior engineers / hiring manager: name, title,
   profile URL, one hook each (recent post or activity, check their last 2-3 posts).
   - Add each person through `POST /api/people`, append a dossier `research`
     activity, then log status=people-mined, people, hooks using the webhook in
     `AGENTS.md`.
   - Do NOT send connection requests in this session.
5. End: summary table + dossier-event count + Sheet-row count + portal queue.

Stop at 10 applications or 50 minutes.
