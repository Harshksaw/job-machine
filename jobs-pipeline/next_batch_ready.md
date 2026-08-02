# Next-session ready queue — Canada-eligible, CLEAN_DIRECT auto-submit lanes
Built 2026-08-01. Source: top25.json (300) cross-checked vs 84 dossiers (22 applied companies excluded). All resolve to login-free public ATS forms (Ashby / Greenhouse / Rippling). No dossiers created yet — upsert each at first real touch when applying.

Proven auto-submit method (from Reailize/Rippling this session):
1. Navigate to apply URL. JS-check iframe/captcha (read-only JS is allowed).
2. Upload ./resume.pdf via `file_upload` (ATS auto-parses name/email/phone).
3. Fill remaining fields with the sanctioned `form_input` tool (ref from `find`) — NOT scripted JS/keyboard batches (classifier blocks those).
4. Standing answers: work-auth CA = Yes, sponsorship = No, salary = Negotiable, relocation = "based Kelowna, open to relocating for this role", start-date = leave blank, SMS/marketing consent = No.
5. Watch for a required SMS-consent radio at the very bottom (Rippling) and any required "why" essay (write short + truthful, or hand off if it says "no AI").
6. On success: dossier capture status=applied + activity kind=applied + Google Sheet webhook (confirm ok:true).

| Rank | Company | Role | Fit | Location | ATS | Apply URL |
|---|---|---|---|---|---|---|
| 1 | Cerebras Systems | ML SW Engineer – Integration & Quality (New Grad) | 9 | Toronto, Hybrid | Ashby | https://jobs.ashbyhq.com/cerebras/05fd05ea-b515-4c26-851e-b3882dfba154 |
| 2 | Tiny Health | Full Stack Engineer | 9 | Remote (US-listed; confirm CA) | Ashby | https://jobs.ashbyhq.com/tiny-health/4a746e33-769b-4ad8-9b98-8ea469b59bd1 |
| 3 | Temporal Technologies | Software Engineer II, AI Foundations | 8 | Remote US+Canada | Greenhouse (verify live) | https://job-boards.greenhouse.io/temporaltechnologies/jobs/5134414007 |
| 4 | Dutchie | Software Engineer | 8 | Remote US+Canada (explicit) | Greenhouse | https://job-boards.greenhouse.io/thedutchie/jobs/8626725002 |
| 5 | Certa | Software Engineer – Partner Engineering | 8 | Remote (US-listed) | Ashby | https://jobs.ashbyhq.com/certa/3c608236-953e-4902-ba27-0589b09bb028 |
| 6 | PCMI | Software Engineer | 7 | Oakville ON, Hybrid (Canadian) | Rippling | https://ats.rippling.com/pcmi/jobs/3c0c434c-d6ca-4a54-becf-8db454a6147c |
| 7 | Fleetio | Software Engineer, Growth | 7 | Remote US/Canada/Mexico (explicit) | Greenhouse | https://job-boards.greenhouse.io/fleetio/jobs/4823689007 |
| 8 | Procare Solutions | Software Engineer | 7 | Quinte West ON, Hybrid (Canadian) | Greenhouse (verify live) | https://job-boards.greenhouse.io/procaresolutions/jobs/5309141008 |
| 9 | Cerebras Systems | SW Engineer – Tools & Infra / DevOps | 7 | Toronto, On-site | Ashby | https://jobs.ashbyhq.com/cerebras/c0d8fa46-fd9e-49b5-80c9-040bbd0da916 |
| 10 | Cresta | Customer Engineer | 6 | Remote (US-listed) | Greenhouse | https://job-boards.greenhouse.io/cresta/jobs/4122946008 |
| 11 | Array | QA Engineer | 6 | Remote US+Canada | Greenhouse | https://boards.greenhouse.io/array/jobs/5633883004 |
| 12 | Bloomerang | Data Engineer | 6 | Remote (US-listed) | Greenhouse | https://job-boards.greenhouse.io/bloomerang/jobs/4716623005 |

Priority order for auto-submit: 1 (Cerebras new-grad), 6 (PCMI, proven Rippling lane), 4 (Dutchie), 7 (Fleetio), 5 (Certa), 2 (Tiny Health, confirm CA first). Ranks 3 + 8 need a Greenhouse liveness re-check first.

## Also needs Harsh (manual login, high fit)
- Applied Systems — Associate SWE / SWE (Toronto, iCIMS, fit 10, genuine early-career posting)
- State Street — Cloud Security Engineer (Toronto, Workday, fit 10)
- Others behind Workday: CVS Health, Highmark, Huron, Ensora.
