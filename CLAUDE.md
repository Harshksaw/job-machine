# Job Machine — persistent context (loaded every session)

## Who I am
Harsh Saw — final-year Computer Information Systems student, Okanagan College (grad Dec 2026), Kelowna BC, Canada. 2+ years internship experience.
- **Current:** SWE Intern @ OmMuse (Seattle, Nov 2025–present) — RAG semantic search (MongoDB Vector Store, AWS Bedrock); Go async HubSpot CRM sync for 12K+ user music platform (sync.Map dedup, 8 API trigger points); Electron desktop uploader (chokidar+SQLite WAL folder sync, S3 multipart, OAuth 2.0 PKCE, 70+ gRPC methods over typed IPC); polyglot monorepo (Go/TS/Python, Bazel, Pulumi, Envoy, GitHub Actions).
- **Bwisher (Dec 2024–Jun 2025):** Kafka + BullMQ multi-channel marketing platform (SMS/email/WhatsApp, 30K+ users); idempotent NestJS/FastAPI payment microservices (retry + exponential backoff); Jenkins/K8s/Prometheus/Grafana; feature-flag rollouts.
- **MoreThinks (Jun–Sept 2025):** Qwik.js + SurrealDB monorepo, AWS EKS, token/vector-embedding pipelines for ML recommendations.
- **Jythu (Jan–Dec 2024):** 2 production React Native apps (LMS + admin, 2K+ learners), Terraform AWS infra, device-bound anti-piracy auth; FFmpeg HLS pipeline (S3/CloudFront/SQS/Lambda/SNS) — seek 30s→1.5s, ~70% bandwidth cut.
- **Projects:** Document Intelligence Platform — multi-tenant RAG (FastAPI/LangChain/Qdrant, Groq→Gemini failover, ECS Fargate, SHA-256 idempotent ingestion). CodeExpo — browser IDE (Docker sandboxes, xterm.js/WebSocket terminal, Monaco, Zustand).
- **Also:** sole dev of LMS migration platform at Okanagan College used daily by 1,500+ staff; XGBoost stock pipeline (500 tickers, 26 horizons, 4x H100); top 2% Freelancer.com; hackathon winner.

## Stack
TypeScript, Python, Go, Bash | React/Next.js/React Native/Qwik/Electron | NestJS, FastAPI, Express, GraphQL, gRPC, Kafka, BullMQ, RabbitMQ | Postgres, Mongo, DynamoDB, Redis, SurrealDB | AWS, Azure, Docker, K8s, Terraform, Pulumi, Bazel, Jenkins, GH Actions | LangChain, RAG, Qdrant, FAISS, Pinecone, Bedrock, AutoGen

## Targeting
Software Engineer / Full-Stack / Backend / AI-ML / Mobile (React Native). New grad or early career. Startups preferred. Open to relocation. Skip listings with hard "no sponsorship ever" language — pause and ask me if wording is ambiguous. No salary floor, no remote-only restriction.

## Discovery sources
Search and apply via LinkedIn, Wellfound, and company ATS only. There is **no**
RDS `job_registry`, no `jobs-pipeline/`, and no local Postgres jobs mirror.
Do not start Docker for a jobs DB, do not look for `RDS_DSN`, and do not treat
"RDS discovery lane is down" in old session notes as a current task. Existing
dossiers with `source: job_registry (RDS)` stay as historical records.

## Contact / links
mister.harshkumar@gmail.com | +1 (778) 583-2260 | linkedin.com/in/harsh-kumar-s-32727b247 | github.com/Harshksaw | harshsaw.me
Resume: ./resume.pdf (use for every upload field)

## Local job dossiers (MANDATORY during every search/apply session)
The local dashboard at `http://127.0.0.1:8420/` is the detailed system of
record. Google Sheets remains the compact pipeline log.

At the first touch of EVERY listing (including low-fit results), upsert its dossier and
keep the returned `id` for the rest of that listing. Status must be one of:
`discovered`, `researching`, `ready`, `applying`, `applied`, `outreach`,
`interview`, `offer`, `rejected`, `skipped`, `archived`.
```
POST http://127.0.0.1:8420/api/jobs/capture
Content-Type: application/json
{
  "company": "...",
  "role": "...",
  "job_url": "...",
  "source": "LinkedIn",
  "location": "...",
  "work_mode": "...",
  "status": "discovered",
  "fit_score": 1,
  "jd_text": "<complete listing text>",
  "company_context": "<specific product/company research>",
  "notes": "<brief decision context>",
  "next_action": "...",
  "session": "<source> <YYYY-MM-DD>"
}
```

After EVERY meaningful action or decision, append a dossier event:
```
POST http://127.0.0.1:8420/api/jobs/<id>/activity
Content-Type: application/json
{
  "kind": "research|decision|applied|outreach|reply|interview|note",
  "title": "<short exact event>",
  "detail": "<what happened, answer submitted, confirmation, or reason>",
  "session": "<source> <YYYY-MM-DD>",
  "occurred_at": null,
  "external_id": null
}
```

For every application, build the evidence-backed kit first:
`POST /api/jobs/<id>/generate-kit?session=<session>`. Use its cover letter when
the form asks for one. For an unusual question, call
`POST /api/jobs/<id>/answers/generate` with `{question,constraints,session}`;
use the saved answer only after checking it. The endpoint intentionally returns
`needs_user_input=true` for salary, sponsorship/authorization, start-date, and
other unknown personal judgments. Never bypass that flag.

When tailoring, include `job_id`, `job_url`, and `session` in the existing
`POST /tailor` body. This attaches the PDF to the dossier and logs the artifact.

## Sheet logging (MANDATORY after external actions)
Webhook — open as URL via playwright (URL-encode values), confirm `{"ok":true}`:
```
https://script.google.com/macros/s/AKfycbz4hpb7VnQIsHEiOyN6wa-7R254QOdo3n0QK-pNw7gJ52a3BbKltIx0pY1PqYkfD2SJLA/exec?company=&role=&source=&jobUrl=&status=&fit=&people=&hooks=&outreach=&notes=
```
Statuses: applied | people-mined | outreach-sent | outreach-queued | replied | interview | rejected

## Hard rules
1. NEVER fabricate experience, skills, dates, or numbers. Every claim traces to this file.
2. Fit score 1–10 before any apply. Below 6 = retain for review: keep the
   dossier active, save the reason/gaps, and never mark it skipped or archive
   it automatically. The user may improve or reconsider it later. 8+ =
   people-mining eligible.
3. LinkedIn: human pace only. Max 12 connection requests per session. Every outreach message shown to me for approval BEFORE sending — no exceptions.
4. Wellfound note field = custom per company: their product/mission hook → one relevant real project of mine → genuine close. 3–4 sentences. No "I'm passionate about."
5. Pause and ask me only for: any dossier answer marked `needs_user_input`,
   ambiguous sponsorship wording, unusual questions the validated answer flow
   cannot resolve, salary questions, or anything requiring a judgment call
   about me.
6. One-line summary per company as you go. Otherwise don't ask permission
   between listings.
7. Never leave a browser action only in chat. The dossier event must be written
   before moving to the next listing; sheet logging is additionally required
   after submissions, outreach, replies, interviews, and rejections.
