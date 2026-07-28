# Wellfound session (target: ~10-12 applications + curated outreach, ~45-60 min)

Use playwright mcp. My profile, rules, and webhook are in CLAUDE.md — follow them exactly.
Set one session label at the start: `Wellfound <YYYY-MM-DD>`. Use it on every
dossier capture, artifact request, answer, activity event, and People record.

1. Open wellfound.com/jobs (I'm already logged in via the persistent profile).
2. Search wide — run each title, take the union: "Software Engineer",
   "Backend Engineer", "AI Engineer", "Full-Stack Engineer", plus the internship
   variants ("Software Engineer Intern", "Backend Intern", "AI/ML Intern").
   - Seniority band: **internship through ~3 years experience.** KEEP internships,
     new-grad, junior, and mid roles that ask for up to 3 YoE. Skip only hard
     senior/staff/lead or 4+ YoE-required listings.
   - Filters: 1-50 employees preferred, posted this week first.
3. Per listing: read the complete job + the company's Wellfound profile. Score
   fit 1–10, then immediately call `/api/jobs/capture` exactly as specified in
   CLAUDE.md. Save the returned dossier `id`.
   - For every score, call
     `POST /api/jobs/<id>/generate-kit?session=<session>` and review its
     evidence, gaps, and recommendation.
   - < 6: keep `status=researching`, set a concrete review `next_action`, and
     add a `decision` activity with the reason and gaps. Never mark it skipped
     or archive it automatically; keep the generated draft for later changes,
     then move to the next listing without submitting it in this session.
   - ≥ 6: use its saved cover letter if the form asks for one.
   - ≥ 6 before uploading, call the resume-tailor-service with the dossier link:
     `{"jd_text":"<complete JD>","company":"<company>","role":"<role>","job_url":"<url>","job_id":"<id>","session":"<session>"}`
     and use the returned `pdf_path`. If it errors, use `./resume.pdf` and add a
     dossier activity describing the fallback.
   - ≥ 6 for any nonstandard form question, call
     `/api/jobs/<id>/answers/generate`; if it marks `needs_user_input`, pause.
   - ≥ 6 submit, capture `status=applied`, append an `applied` activity containing
     the form/confirmation details, then log the compact Sheet row.
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
   - Append a `research` activity to the dossier, then log the Sheet row:
     status=people-mined, people={names, titles, profile URLs}, hooks={one per person}.
5. Curated LinkedIn outreach — draft, batch-approve, then send (in this session):
   - Draft one connection-request note per curated person. Framing: lead with a
     shipped production win of mine (e.g. Go async HubSpot sync, RAG semantic
     search, FFmpeg HLS pipeline) mapped to a concrete problem their company is
     solving — "here's how I solved a problem you're working on." Experienced-hire
     tone; do NOT open with "I'm a student/intern looking for…". ≤ 300 chars,
     custom per company (CLAUDE.md rule 4). No fabrication — never claim a title,
     seniority, or years I don't have; every claim traces to CLAUDE.md.
   - Save each note as the person's `message` and set `status=queued`.
   - Cap at **12 connection requests this session** (highest-fit companies first).
     Anything beyond 12 stays `to-reach`/`queued` for a later session — say so.
   - STOP and show me the full batch in one view (person | company | note) for
     approval/edits BEFORE sending anything — no exceptions (CLAUDE.md rule 3).
   - Only after I approve: send each LinkedIn connect-with-note at human pace,
     set the person `status=sent`, append an `outreach` activity to that company's
     dossier, and log the Sheet row (status=outreach-sent, people, hooks, outreach).
6. End of session: summary table (company | role | fit | applied? | people found |
   notes queued/sent), number of dossier events written, number of Sheet rows
   logged, and any people/notes held over the 12-cap for next session.

Work through listings continuously. Stop after 12 applications or when results
run dry, whichever first.
