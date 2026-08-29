# Wellfound session (target: ~10-12 applications + curated outreach, ~45-60 min)

Read `AGENTS.md` first (hard rules, eligibility, dossier + sheet contracts). Then
`docs/AGENT-PLAYBOOK.md` for `__NEXT_DATA__` JD harvest, `atsSource` routing, and
inert-submit checks, and `docs/PERSONAL-ANSWERS.md` before filling any form field.
Use playwright mcp. Follow `AGENTS.md` exactly for capture, kit, answers, resume
upload, and sheet logging.

Set one session label at the start: `Wellfound <YYYY-MM-DD>`. Use it on every
dossier capture, artifact request, answer, activity event, and People record.

1. Open wellfound.com/jobs (already logged in via the persistent profile).
2. Search wide — run each title, take the union: "Software Engineer",
   "Backend Engineer", "AI Engineer", "Full-Stack Engineer", plus the internship
   variants ("Software Engineer Intern", "Backend Intern", "AI/ML Intern").
   - Seniority band: **internship through ~3 years experience.** KEEP internships,
     new-grad, junior, and mid roles that ask for up to 3 YoE. Skip only hard
     senior/staff/lead or 4+ YoE-required listings.
   - Filters: 1-50 employees preferred, posted this week first.
3. Per listing: read the complete job + the company's Wellfound profile. Score
   fit 1–10, capture the dossier per `AGENTS.md`, and save the returned `id`.
   Generate the kit (including below-6 listings) and any unusual-question answers
   per `AGENTS.md`. Pause on `needs_user_input`.
   - Fit below 6: retain for review per `AGENTS.md` rule 2, then next listing.
   - Fit 6+: use the saved cover letter if the form asks for one. If the apply
     form has a note field, write it per `AGENTS.md` rule 4. Upload `./resume.pdf`
     as-is unless the role truly requires a tailored PDF (confirm with Harsh
     first; see `AGENTS.md`). Submit, mark applied, append an `applied` activity
     with form/confirmation details, then log the sheet row using the webhook in
     `AGENTS.md`. Prefer the company's own ATS when `atsSource` is present (see
     playbook).
4. People + email capture (every applied company):
   - Capture the founders shown on the Wellfound company profile (names +
     titles). If fit ≥ 8, also open the company's site /team or /about and their
     GitHub org if linked — capture engineers + one real hook each (recent
     launch, funding, repo, post).
   - Find a public email for each person (company /team page, GitHub profile,
     personal site). Do NOT guess or pattern-invent an address — only record one
     that is actually published somewhere.
   - Add each person via `POST /api/people` with the exact company/role, the
     LinkedIn profile URL, `status=to-reach`, `hook`, and any real email stored
     as a link (`links:[{"label":"email","url":"mailto:<addr>"}]`) plus the raw
     address in `notes`. If no public email exists, record the person without one.
   - Append a `research` activity to the dossier, then log status=people-mined
     using the webhook in `AGENTS.md`.
5. Curated LinkedIn outreach — draft, batch-approve, then send (in this session):
   - Draft one connection-request note per curated person. Framing: lead with a
     shipped production win from the resume bank mapped to a concrete problem
     their company is solving — "here's how I solved a problem you're working on."
     Experienced-hire tone; do NOT open with "I'm a student/intern looking for…".
     ≤ 300 chars (LinkedIn note cap; see playbook). Custom per company. No
     fabrication — every claim traces to `resume-tailor-service/content/resume_bank.yaml`.
   - Save each note as the person's `message` and set `status=queued`.
   - Cap sends per `AGENTS.md` rule 3 (highest-fit companies first). Anything
     beyond the cap stays `to-reach`/`queued` for a later session — say so.
   - STOP and show the full batch in one view (person | company | note) for
     approval/edits BEFORE sending anything (`AGENTS.md` rule 3).
   - Only after approval: send each LinkedIn connect-with-note at human pace,
     set the person `status=sent`, append an `outreach` activity to that company's
     dossier, and log status=outreach-sent using the webhook in `AGENTS.md`.
6. End of session: summary table (company | role | fit | applied? | people found |
   notes queued/sent), number of dossier events written, number of Sheet rows
   logged, and any people/notes held over the send cap for next session.

Work through listings continuously. Stop after 12 applications or when results
run dry, whichever first.
