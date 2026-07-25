# LinkedIn session (target: ~8-10 applications, human pace, ~50 min)

Use playwright mcp. Profile, rules, webhook in CLAUDE.md. LinkedIn = my
networking asset: human pace, natural pauses between actions, nothing bulk.
Set one session label at the start: `LinkedIn <YYYY-MM-DD>`. Use it on every
dossier capture, artifact request, answer, and activity event.

1. Open linkedin.com/jobs (logged in via persistent profile).
2. Search: "Software Engineer New Grad", "Backend Engineer", "Full Stack Engineer",
   "AI Engineer" — filter: posted past week, then past 24h for a second pass.
   Prioritize Easy Apply + small companies.
3. Per listing: read the complete JD, score fit 1–10, then immediately call
   `/api/jobs/capture` as specified in CLAUDE.md and retain the dossier `id`.
   - For every score, call
     `POST /api/jobs/<id>/generate-kit?session=<session>` and check its
     evidence/gaps.
   - < 6: keep `status=researching`, set a concrete review `next_action`, and
     append a `decision` activity with the reason and gaps. Never mark it
     skipped or archive it automatically; keep the generated draft so it can
     be changed and reconsidered later.
   - ≥ 6: for each nonstandard free-text question, call
     `/api/jobs/<id>/answers/generate`; pause on `needs_user_input`.
   - ≥ 6 Easy Apply: fill with verified facts. Before uploading, call `/tailor`
     with `jd_text`, `company`, `role`, `job_url`, `job_id`, and `session`; use
     the returned `pdf_path`. On error, use `./resume.pdf` and add a dossier
     fallback activity. Use the dossier cover letter when requested. Submit,
     capture `status=applied`, and append an `applied` activity.
   - ≥ 6 external-redirect: if the external form is quick (Lever/Ashby style),
     complete it; if it's a Workday/Greenhouse marathon, set dossier
     `status=applying`, `next_action=Complete portal application`, append a
     `decision` activity, log status=outreach-queued and notes=portal-queue,
     then move on.
   - Log every completed apply to the Sheet: status=applied, source=LinkedIn,
     fit, notes.
4. Small startups (<50 people) with fit ≥ 8: open company page → People tab.
   Capture founders / founding-senior engineers / hiring manager: name, title,
   profile URL, one hook each (recent post or activity — check their last 2-3 posts).
   - Add each person through `POST /api/people`, append a dossier `research`
     activity, then log status=people-mined, people, hooks to the Sheet.
   - Do NOT send connection requests in this session.
5. End: summary table + dossier-event count + Sheet-row count + portal queue.

Stop at 10 applications or 50 minutes.
