# Wellfound session (target: ~10-12 applications, ~45 min)

Use playwright mcp. My profile, rules, and webhook are in CLAUDE.md — follow them exactly.

1. Open wellfound.com/jobs (I'm already logged in via the persistent profile).
2. Search: "Software Engineer" then "Backend Engineer" then "AI Engineer" — filters: 1-50 employees preferred, posted this week first.
3. Per listing: read the job + the company's Wellfound profile. Score fit 1–10.
   - < 6: skip, one-line reason.
   - ≥ 6: apply. Before uploading, call the resume-tailor-service:
     `curl -s --max-time 300 -X POST http://localhost:8420/tailor -H "Authorization: Bearer $RESUME_TAILOR_TOKEN" -H "Content-Type: application/json" -d '{"jd_text": "<listing JD text>", "company": "<company>", "role": "<role>"}'`
     and use the returned `pdf_path` for the resume upload. If the service
     isn't running or errors, fall back to `./resume.pdf` and note the
     fallback in the session summary. Custom note per rule 4 in CLAUDE.md.
   - Log: status=applied, source=Wellfound, include fit + condensed note in notes.
4. For every applied company: note the founders shown on the Wellfound company
   profile (names + titles). If fit ≥ 8, also open their website /team or /about
   page and their GitHub org if linked — capture engineers + one hook each
   (recent launch, funding, repo, post).
   - Log a second row: status=people-mined, people={names, titles, profile URLs}, hooks={one per person}.
5. Do NOT send any outreach in this session — that's the outreach prompt's job.
6. End of session: summary table (company | role | fit | applied? | people found)
   and tell me how many rows were logged.

Work through listings continuously. Stop after 12 applications or when results
run dry, whichever first.
