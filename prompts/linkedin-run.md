# LinkedIn session (target: ~8-10 applications, human pace, ~50 min)

Use playwright mcp. Profile, rules, webhook in CLAUDE.md. LinkedIn = my
networking asset: human pace, natural pauses between actions, nothing bulk.

1. Open linkedin.com/jobs (logged in via persistent profile).
2. Search: "Software Engineer New Grad", "Backend Engineer", "Full Stack Engineer",
   "AI Engineer" — filter: posted past week, then past 24h for a second pass.
   Prioritize Easy Apply + small companies.
3. Per listing: score fit 1–10.
   - < 6: skip, one-line reason.
   - ≥ 6 Easy Apply: fill from CLAUDE.md, resume = ./resume.pdf, short real
     answers for free-text (never fabricate). Submit.
   - ≥ 6 external-redirect: if the external form is quick (Lever/Ashby style),
     complete it; if it's a Workday/Greenhouse marathon, log it with
     status=outreach-queued and notes=portal-queue instead, and move on.
   - Log every apply: status=applied, source=LinkedIn, fit, notes.
4. Small startups (<50 people) with fit ≥ 8: open company page → People tab.
   Capture founders / founding-senior engineers / hiring manager: name, title,
   profile URL, one hook each (recent post or activity — check their last 2-3 posts).
   - Log: status=people-mined, people, hooks.
   - Do NOT send connection requests in this session.
5. End: summary table + logged row count + list of portal-queued items.

Stop at 10 applications or 50 minutes.
