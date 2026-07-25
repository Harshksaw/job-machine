# Session log — LinkedIn Easy-Apply run (2026-07-24)

Ran `prompts/linkedin-run.md`. Human-paced, per-listing fit scoring, tailored
resume per apply, every apply logged to the tracking webhook (each confirmed
`{"ok":true}`).

## Result: 5 applications submitted ✅

| Company | Role | Fit | Job ID | Notes |
|---|---|---|---|---|
| **VAZA** | Full Stack Software Engineer | 7 | 4444022729 | Toronto consumer startup (200K users, $10M vol). Strong AWS ECS/S3-CloudFront/Terraform/GH-Actions + payments match; Rust/Vue gaps (they ramp). Hybrid GTA → answered GTA-location & Waterloo-degree screening honestly (No). |
| **Enerva Energy Solutions** | Software Engineer | 8 | 4443156571 | Employee-owned cleantech, small Calgary team, "new grads welcome." Python/TS/React/SQL + AI-LLM tooling bullseye. On-site Calgary (relocation OK). |
| **Reklaim** | AI-Native Full-Stack Engineer | 8 | 4443540363 | Remote data-ownership startup, AI-native/Cursor-agents daily. React/TS/Next + Postgres + AWS EKS/RDS + GH Actions + agentic-AI match; Supabase/Deno & PostHog gaps transferable. |
| **StackAdapt** | Full Stack Engineer | 8 | 4424750255 | Ad-tech scale-up, remote (BC posting). Go + React + GraphQL + MCP/AI-agents; meets 2+yr full-stack req; Ruby optional. (They posted 4 city-variants — applied to ONE.) |
| **Hunter Bond** (Elite Quant Fund client) | Junior Software Engineer (Python) | 7 | 4440428756 | Front-office quant fund, Python real-time risk/pricing. Hook = XGBoost stock-prediction pipeline + Python/CS. Hybrid Montreal (relocation). Recruiter-mediated. |

## Skipped (with one-line reason)

- **Innodata** — AI/ML Research Engineer (LLM Post-Training) · fit 5 · core req is hands-on LLM fine-tuning/post-training; Harsh is applied-RAG, not model training.
- **Copia Wealth Studios** — Full Stack · fit 5 · great tech fit but hard "minimum 7 years experience."
- **Escalent** — AI Transformation Developer · fit 5 · required 5–8 yrs Python.
- **DeOS** — Junior SWE (New Grad) · fit 5 · #1 responsibility is real-time game-streaming in **C++** (Harsh has none); 100% on-site Montreal.
- **SayVo AI** — Entry-Level Developer · **user-declined** · excellent fit BUT gated on immediate, all-in, full-time-only availability ("not for anyone with another job"); Harsh is interning + student.
- **Spade Group** — Full Stack · skip · Node/React/TS/Claude-Code/MCP is a bullseye, but it's **part-time 15–20 hrs/wk @ $25/hr contract**, not a full-time role. *(Revisit if part-time is ever wanted.)*
- **Astek** — Python Developer · fit 5 · strong stack match but hard 6+ years requirement.

## Standing facts established this session (reuse next time — don't re-ask)

- **Work authorization:** authorized to work in **Canada, NO sponsorship needed.**
  → answer "legally authorized to work" = **Yes**, "require sponsorship now/future" = **No**.
- **Salary expectation:** **Negotiable / Open** (no floor).
- **Location:** Kelowna, BC. NOT in/near GTA or Toronto. Open to relocation, but
  answer "are you located in <city>?" **honestly by current location** (usually No).
- **Availability:** currently SWE intern @ OmMuse + final-year student (grad Dec 2026).
  NOT available for "immediate, all-in, drop-your-other-job" roles → that's why SayVo was declined.
- **English proficiency:** Professional. **Ruby/RoR:** none (pick lowest bucket).
  **React/React Native:** ~1–2 yrs. **Total professional experience:** ~2 yrs (1–3 bucket).
  **AI tools:** "regularly use … with concrete examples."

## LinkedIn search recipe that worked

```
https://www.linkedin.com/jobs/search/?keywords=<KW>&f_AL=true&f_TPR=r604800&f_E=1,2,3&geoId=101174742&sortBy=DD
```
- `f_AL=true` Easy Apply · `f_TPR=r604800` past week · `f_E=1,2,3` intern/entry/associate ·
  `geoId=101174742` Canada · `sortBy=DD` most recent.
- **Always add `f_E`** — the plain keyword search ignores seniority and floods you with 5–8 yr roles.
- Keywords used: "Software Engineer New Grad", "Software Engineer", "Full Stack Developer".
  **Next to try:** "Backend Developer", "AI Engineer" (entry-level, Canada).
- **Aggregators/staffing to skip:** Crossing Hurdles, Turing ($300/hr gig), Robert Half, NLB
  Services, Insight Global, Jobgether (reposts), Apexon, Highspring, Agilus, CGI, generic
  Hunter Bond reposts. (Direct-employer, right-level roles are the signal.)
- Extract job lists compactly via JS (scroll each `li[data-occludable-job-id]` into view to
  force lazy-render) instead of huge accessibility snapshots.

## Resume-tailor flow (per apply)

- Service: `http://localhost:8420` — **local-only, NO auth on this branch** (no token needed).
  Start with `resume-tailor-service/scripts/start.sh`.
- Call: `POST /tailor` with `{"jd_text","company","role"}` → returns `{"pdf_path",...}`.
- ~90–150 s per call (LLM via `claude` CLI) — give any shell wrapper a **>300 s timeout**.
- Output lands at `resume-tailor-service/output/<slug>/resume.pdf` (gitignored — regenerable).
- Every tailored resume this session pulled the *right* real content from the bank
  (payments/AWS for VAZA, RAG/LLM for Enerva/Reklaim, Go/gRPC for StackAdapt, the stock
  ML pipeline for the quant fund) — the service validates against the bank, so no fabrication.

## Logging webhook

Open the Apps Script `/exec` URL in the browser (URL-encoded), confirm `{"ok":true}`.
Statuses: `applied | people-mined | outreach-sent | outreach-queued | replied | interview | rejected`.

## To resume

1. `cd resume-tailor-service && ./scripts/start.sh` (window 1)
2. `claude` (window 2) → "run the linkedin prompt"
3. Continue from "Backend Developer" / "AI Engineer" searches; the standing facts above
   answer most screening questions without pausing.
