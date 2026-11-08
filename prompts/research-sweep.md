# Research sweep across job portals (Cursor or OpenCode)

Read `AGENTS.md` first (eligibility, claim rule) and the newest `SESSION-HANDOFF-*.md`.
This run **only researches**. It never applies, never sends outreach, and never writes
dossiers directly: every find goes to the research stage, and Harsh (or Claude) promotes
the good ones from the dashboard Search tab.

## Who we are looking for

Early career software engineer (about 2 years of professional work, graduating Dec 2026):
backend and full stack, applied AI (RAG, agents, LLM integration), forward deployed and
platform roles. Full time. Read `resume-tailor-service/content/resume_bank.yaml` for the
real experience before judging fit.

Where he can work (see AGENTS.md eligibility): anywhere in Canada; US roles that sponsor or
are silent on sponsorship; remote roles that allow living in Canada. UK and Australia
remote roles count only when the posting allows hires outside that country (worldwide,
Americas, Canada). Skip senior, staff, lead, manager, and on site outside the US and Canada.

## Where to look (no login needed unless noted)

| Portal | How |
|---|---|
| Ashby, Greenhouse, Lever boards | public posting APIs (see playbook "Fetching full JD text") |
| Himalayas, Remotive, Jobicy, Working Nomads, Remote OK | `uv run python scripts/remote_boards.py --out <file>` |
| Hacker News "Who is hiring" (current month) | thread page, filter REMOTE and Canada |
| YC Work at a Startup | public job pages |
| Wellfound | Ego Lite, Harsh is logged in; read only |
| We Work Remotely, Built In, Welcome to the Jungle | public listing pages |

Use the free tools first. Fantastic Jobs credits are limited (500 jobs on the trial): use
only the dashboard presets for it, never raw calls.

## How to stage a find

```
POST http://127.0.0.1:8420/api/research
X-Job-Machine: dashboard
Content-Type: application/json
{
  "company": "...", "role": "...", "url": "<employer ATS url when you can find it>",
  "source": "Cursor sweep: <portal>", "location": "...",
  "remote_scope": "<where remote hires may live, as written>",
  "open_to_canada": true|false|null,
  "visa": "<sponsorship text if any>", "salary": "...", "posted": "YYYY-MM-DD",
  "jd_text": "<full description>", "notes": "<one line why it fits>",
  "preset": "portal-sweep"
}
```

The endpoint dedupes on url and reports `tracked_dossier` when a dossier already exists;
skip those. Prefer the employer's own ATS url over an aggregator url.

## Finish

Stop at 40 staged items or 60 minutes. End with a table: portal | found | staged |
skipped (already tracked, ineligible, senior). No em dashes or hyphenated compounds in
notes.
