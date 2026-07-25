# Wellfound session (target: ~10-12 applications, ~45 min)

Use playwright mcp. My profile, rules, and webhook are in CLAUDE.md — follow them exactly.
Set one session label at the start: `Wellfound <YYYY-MM-DD>`. Use it on every
dossier capture, artifact request, answer, and activity event.

1. Open wellfound.com/jobs (I'm already logged in via the persistent profile).
2. Search: "Software Engineer" then "Backend Engineer" then "AI Engineer" — filters: 1-50 employees preferred, posted this week first.
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
4. For every applied company: note the founders shown on the Wellfound company
   profile (names + titles). If fit ≥ 8, also open their website /team or /about
   page and their GitHub org if linked — capture engineers + one hook each
   (recent launch, funding, repo, post).
   - Add each person through `POST /api/people` with the exact company/role,
     profile URL, hook, and `status=to-reach`.
   - Append a `research` activity to the dossier, then log the second Sheet row:
     status=people-mined, people={names, titles, profile URLs}, hooks={one per person}.
5. Do NOT send any outreach in this session — that's the outreach prompt's job.
6. End of session: summary table (company | role | fit | applied? | people
   found), number of dossier events written, and number of Sheet rows logged.

Work through listings continuously. Stop after 12 applications or when results
run dry, whichever first.
