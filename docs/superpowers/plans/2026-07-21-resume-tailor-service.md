# Resume Tailor Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local/VPS-deployable FastAPI service that takes a job description and returns the user's real resume, tailored by selecting/reordering existing content (never fabricating), compiled to a guaranteed one-page PDF via the user's real `resume.cls`.

**Architecture:** FastAPI app (`resume-tailor-service/app/`) backed by a YAML content bank (`content/resume_bank.yaml`) that is the only source of real resume facts. One Anthropic call produces a JSON "manifest" (IDs + order only, never freeform bullet text) for a given job description; the manifest is validated against the bank before anything is rendered; a Jinja2 template + the user's real `resume.cls` + local `pdflatex` produce the PDF; a trim-and-recompile loop guarantees exactly one page.

**Tech Stack:** Python 3.11+, `uv` (dependency management), FastAPI, Pydantic, Jinja2, `anthropic` SDK, `pypdf`, local `pdflatex`, Docker (for VPS deploy), pytest.

## Global Constraints

- Dependencies managed exclusively via `uv` in `resume-tailor-service/` — no global pip installs.
- No resume content may originate anywhere except `content/resume_bank.yaml`. The Anthropic call returns IDs and order only; any manifest referencing an unknown ID is rejected, not sanitized/guessed.
- The compiled PDF must be exactly one page. If it isn't after the full trim sequence, the service returns an explicit error — it never returns a >1 page PDF.
- `/tailor` requires a valid `Authorization: Bearer <RESUME_TAILOR_TOKEN>` header in every deployment mode (local and VPS) — checked with `hmac.compare_digest`, never plain `==`. `/health` requires no auth and returns no secrets.
- `.env` (real secrets) is gitignored (already covered by the repo's root `.gitignore`); only `.env.example` is committed.
- The user's real `templates/resume.cls` (Trey Hunner / LaTeXTemplates.com, freely licensed) is used as-is — its license header must remain intact.
- Every task ends with a command the engineer actually runs, with the expected output stated.

---

### Task 1: Project scaffold — `pyproject.toml`, dependencies, `.env.example`

**Files:**
- Create: `resume-tailor-service/pyproject.toml`
- Create: `resume-tailor-service/.env.example`
- Create: `resume-tailor-service/app/__init__.py`
- Create: `resume-tailor-service/tests/__init__.py`

**Interfaces:**
- Produces: an installable `uv` project at `resume-tailor-service/` with `fastapi`, `uvicorn[standard]`, `pydantic`, `jinja2`, `pyyaml`, `pypdf`, `anthropic`, `python-dotenv` as main deps, and `pytest`, `httpx` in the `dev` dependency group (later tasks import all of these).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "resume-tailor-service"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "pypdf>=5.0",
    "anthropic>=0.39",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
RESUME_TAILOR_TOKEN=replace-with-a-long-random-string
```

- [ ] **Step 3: Create empty package markers**

```bash
mkdir -p resume-tailor-service/app resume-tailor-service/tests
touch resume-tailor-service/app/__init__.py
touch resume-tailor-service/tests/__init__.py
```

- [ ] **Step 4: Sync dependencies**

Run (from `resume-tailor-service/`): `uv sync`
Expected: creates `.venv/` and `uv.lock`, exits 0.

- [ ] **Step 5: Verify imports resolve**

Run: `uv run python -c "import fastapi, pydantic, jinja2, yaml, pypdf, anthropic, dotenv; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
cd resume-tailor-service
git add pyproject.toml uv.lock .env.example app/__init__.py tests/__init__.py
git commit -m "resume-tailor-service: scaffold uv project and dependencies"
```

---

### Task 2: Resume content bank — schema, loader, and real data

**Files:**
- Create: `resume-tailor-service/app/bank.py`
- Create: `resume-tailor-service/content/resume_bank.yaml`
- Create: `resume-tailor-service/tests/fixtures/sample_bank.yaml`
- Test: `resume-tailor-service/tests/test_bank.py`

**Interfaces:**
- Produces: `Bullet(id: str, text: str)`, `Job(id, company, location, title, dates, bullets: list[Bullet])`, `Project(id, name, tech, bullets: list[Bullet])`, `Contact(name, phone, location, email, linkedin_url, github_url, website_url, website_display)`, `Education(degree, school, date)`, `SkillLine(category, items)`, `ResumeBank(contact, education, jobs, projects, achievements: list[Bullet], skills: list[SkillLine])` — all Pydantic models in `app/bank.py`.
- Produces: `load_bank(path: pathlib.Path) -> ResumeBank`, `all_job_bullet_ids(bank) -> dict[str, set[str]]`, `all_project_bullet_ids(bank) -> dict[str, set[str]]`, `all_achievement_ids(bank) -> set[str]`, `all_job_ids(bank) -> set[str]`, `all_project_ids(bank) -> set[str]`, `bank_text_blob(bank) -> str` (every bullet/achievement/skill-item text, space-joined, used later for the summary-line fact check).

- [ ] **Step 1: Write the fixture bank used only by tests**

```yaml
# resume-tailor-service/tests/fixtures/sample_bank.yaml
contact:
  name: "Test Person"
  phone: "+1 555-0100"
  location: "Testville, TS"
  email: "test@example.com"
  linkedin_url: "https://linkedin.com/in/testperson"
  github_url: "https://github.com/testperson"
  website_url: "https://testperson.dev"
  website_display: "testperson.dev"

education:
  degree: "Bachelor of Testing"
  school: "Test University"
  date: "Expected Dec 2099"

jobs:
  - id: acme
    company: "Acme Corp"
    location: "Remote"
    title: "Software Engineer"
    dates: "Jan 2024 -- Present"
    bullets:
      - id: acme.bullet.1
        text: "Built a widget pipeline processing 500 widgets per hour."
      - id: acme.bullet.2
        text: "Reduced widget latency by 40 percent."

projects:
  - id: widgetizer
    name: "Widgetizer"
    tech: "Python, Redis"
    bullets:
      - id: project.widgetizer.bullet.1
        text: "Built a caching layer with Redis cutting load time from 4s to 400ms."

achievements:
  - id: achievement.1
    text: "Won the regional Test Hackathon."

skills:
  - category: "Languages"
    items: "Python, Go"
```

- [ ] **Step 2: Write the failing test**

```python
# resume-tailor-service/tests/test_bank.py
from pathlib import Path
import pytest
from app.bank import (
    load_bank, all_job_ids, all_project_ids, all_achievement_ids,
    all_job_bullet_ids, all_project_bullet_ids, bank_text_blob,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"


def test_load_bank_parses_all_sections():
    bank = load_bank(FIXTURE)
    assert bank.contact.name == "Test Person"
    assert bank.education.school == "Test University"
    assert len(bank.jobs) == 1
    assert bank.jobs[0].id == "acme"
    assert len(bank.jobs[0].bullets) == 2
    assert len(bank.projects) == 1
    assert len(bank.achievements) == 1
    assert len(bank.skills) == 1


def test_all_job_ids():
    bank = load_bank(FIXTURE)
    assert all_job_ids(bank) == {"acme"}


def test_all_project_ids():
    bank = load_bank(FIXTURE)
    assert all_project_ids(bank) == {"widgetizer"}


def test_all_achievement_ids():
    bank = load_bank(FIXTURE)
    assert all_achievement_ids(bank) == {"achievement.1"}


def test_all_job_bullet_ids_keyed_by_job():
    bank = load_bank(FIXTURE)
    assert all_job_bullet_ids(bank) == {"acme": {"acme.bullet.1", "acme.bullet.2"}}


def test_all_project_bullet_ids_keyed_by_project():
    bank = load_bank(FIXTURE)
    assert all_project_bullet_ids(bank) == {
        "widgetizer": {"project.widgetizer.bullet.1"}
    }


def test_bank_text_blob_contains_all_bullet_text():
    bank = load_bank(FIXTURE)
    blob = bank_text_blob(bank)
    assert "500 widgets per hour" in blob
    assert "40 percent" in blob
    assert "400ms" in blob
    assert "regional Test Hackathon" in blob
    assert "Python, Go" in blob


def test_load_bank_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_bank(Path("/nonexistent/bank.yaml"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_bank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bank'`

- [ ] **Step 4: Write `app/bank.py`**

```python
from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel


class Bullet(BaseModel):
    id: str
    text: str


class Job(BaseModel):
    id: str
    company: str
    location: str
    title: str
    dates: str
    bullets: list[Bullet]


class Project(BaseModel):
    id: str
    name: str
    tech: str
    bullets: list[Bullet]


class Contact(BaseModel):
    name: str
    phone: str
    location: str
    email: str
    linkedin_url: str
    github_url: str
    website_url: str
    website_display: str


class Education(BaseModel):
    degree: str
    school: str
    date: str


class SkillLine(BaseModel):
    category: str
    items: str


class ResumeBank(BaseModel):
    contact: Contact
    education: Education
    jobs: list[Job]
    projects: list[Project]
    achievements: list[Bullet]
    skills: list[SkillLine]


def load_bank(path: Path) -> ResumeBank:
    if not path.exists():
        raise FileNotFoundError(f"resume bank not found: {path}")
    data = yaml.safe_load(path.read_text())
    return ResumeBank.model_validate(data)


def all_job_ids(bank: ResumeBank) -> set[str]:
    return {job.id for job in bank.jobs}


def all_project_ids(bank: ResumeBank) -> set[str]:
    return {project.id for project in bank.projects}


def all_achievement_ids(bank: ResumeBank) -> set[str]:
    return {bullet.id for bullet in bank.achievements}


def all_job_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {job.id: {b.id for b in job.bullets} for job in bank.jobs}


def all_project_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {proj.id: {b.id for b in proj.bullets} for proj in bank.projects}


def bank_text_blob(bank: ResumeBank) -> str:
    parts: list[str] = []
    for job in bank.jobs:
        parts.extend(b.text for b in job.bullets)
    for proj in bank.projects:
        parts.extend(b.text for b in proj.bullets)
    parts.extend(b.text for b in bank.achievements)
    parts.extend(s.items for s in bank.skills)
    return " ".join(parts)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_bank.py -v`
Expected: 7 passed.

- [ ] **Step 6: Write the real content bank**

Create `resume-tailor-service/content/resume_bank.yaml` using the facts already
approved in the repo's root `CLAUDE.md` and `resume.pdf` (the canonical,
already-fact-checked resume text — transcribe bullets verbatim, do not
reword). Structure:

```yaml
contact:
  name: "Harsh Saw"
  phone: "+1 (778) 583-2260"
  location: "Kelowna, BC, Canada"
  email: "mister.harshkumar@gmail.com"
  linkedin_url: "https://linkedin.com/in/harsh-kumar-s-32727b247"
  github_url: "https://github.com/Harshksaw"
  website_url: "https://harshsaw.me"
  website_display: "harshsaw.me"

education:
  degree: "Bachelor of Computer Information Systems"
  school: "Okanagan College"
  date: "Expected Dec 2026"

jobs:
  - id: ommuse
    company: "Ommuse"
    location: "Seattle, US"
    title: "Software Engineer Intern"
    dates: "Nov 2025 -- Present"
    bullets:
      - id: ommuse.bullet.1
        text: "Architecting AI-powered semantic search and natural language chat for enterprise studio workflows using a RAG pipeline (MongoDB Vector Store, AWS Bedrock), enabling producers to query projects, tracks, and collaborators conversationally."
      - id: ommuse.bullet.2
        text: "Built HubSpot CRM sync for a 12K+ user music platform in Go -- async batch worker using sync.Map deduplication (30s flush, 100-user chunks) syncing live metrics across 8 API trigger points; platform manages 18K+ tracks and 67 GB of user audio."
      - id: ommuse.bullet.3
        text: "Engineered a cross-platform desktop uploader (Electron) with persistent folder-sync engine (chokidar + SQLite WAL), parallelized S3 multipart uploads, OAuth 2.0 PKCE auth flow, and a typed IPC bridge exposing 70+ gRPC service methods to the renderer."
      - id: ommuse.bullet.4
        text: "Shipped features across a polyglot monorepo (Go gRPC/protobuf, TypeScript/React, Python) unified by Bazel, owning full deployment infrastructure -- AWS (S3, SQS, ECR), Docker, Pulumi IaC, Envoy proxy, and GitHub Actions CI/CD."
  - id: morethinks
    company: "MoreThinks Solutions Ltd."
    location: "Burnaby, BC"
    title: "Full-Stack Developer Intern"
    dates: "Jun 2025 -- Sept 2025"
    bullets:
      - id: morethinks.bullet.1
        text: "Developed full-stack features using Qwik.js and SurrealDB in a monorepo, with CI/CD automation via AWS EKS and API Gateway."
      - id: morethinks.bullet.2
        text: "Engineered automated token generation and vector embedding pipelines, producing structured data consumed by ML services for recommendation."
  - id: bwisher
    company: "Bwisher Ltd"
    location: "Remote"
    title: "Software Engineer Intern"
    dates: "Dec 2024 -- Jun 2025"
    bullets:
      - id: bwisher.bullet.1
        text: "Architected a multi-channel marketing platform using Apache Kafka and BullMQ, orchestrating personalized SMS, email, and WhatsApp campaigns with custom offers across 30K+ users while feeding real-time CRM and analytics pipelines."
      - id: bwisher.bullet.2
        text: "Designed idempotent NestJS and FastAPI microservices for payment and credit workflows with retry and exponential backoff strategies, eliminating duplicate transactions in high-stakes financial operations."
      - id: bwisher.bullet.3
        text: "Owned end-to-end deployment infrastructure with Jenkins, Kubernetes, Prometheus, and Grafana; shipped features behind feature flags enabling safe tenant-by-tenant rollouts with instant kill-switch control."
  - id: jythu
    company: "Jythu Ltd"
    location: "Remote"
    title: "Full-Stack Developer Intern"
    dates: "Jan 2024 -- Dec 2024"
    bullets:
      - id: jythu.bullet.1
        text: "Shipped two production React Native apps (LMS + admin panel) with Node.js backends serving 2K+ learners; provisioned full AWS infrastructure with Terraform and GitHub Actions CI/CD, with multi-layer anti-piracy controls including device-bound auth."
      - id: jythu.bullet.2
        text: "Built an end-to-end video streaming pipeline using FFmpeg HLS transcoding delivered via S3/CloudFront, orchestrated through SQS, Lambda, and SNS -- reducing seek time from 30s to 1.5s and cutting bandwidth by approximately 70%."

projects:
  - id: docintel
    name: "Document Intelligence Platform (RAG)"
    tech: "FastAPI, LangChain, Qdrant, Groq, Google Gemini, AWS ECS Fargate, Docker"
    bullets:
      - id: project.docintel.bullet.1
        text: "Architected a multi-tenant RAG platform with session-isolated Qdrant indexes, enabling semantic search and conversational Q&A over PDF, DOCX, and TXT documents."
      - id: project.docintel.bullet.2
        text: "Engineered resilient LLM orchestration using LangChain RunnableWithFallbacks, implementing automatic provider failover (Groq to Gemini) with streaming retrieval pipelines featuring context-aware query rewriting and hybrid document chunking."
      - id: project.docintel.bullet.3
        text: "Deployed to AWS ECS Fargate with GitHub Actions CI/CD and multi-worker Uvicorn scaling; designed idempotent ingestion using SHA-256 fingerprinting to deduplicate embeddings and reduce redundant indexing."
  - id: codexpo
    name: "CodeExpo -- Browser-Based IDE \\& Sandbox Environment"
    tech: "React, Node.js, WebSocket, Docker, Nginx, Zustand, xterm.js"
    bullets:
      - id: project.codexpo.bullet.1
        text: "Engineered a full-stack browser-based IDE replicating a local dev environment -- live terminal via xterm.js and WebSocket, real-time code execution with browser preview pane, and Socket.IO file synchronization across the workspace."
      - id: project.codexpo.bullet.2
        text: "Architected containerized sandbox environments using Docker with multi-stage builds and Nginx reverse proxy, managing isolated execution contexts and environment lifecycle per session."
      - id: project.codexpo.bullet.3
        text: "Delivered a native-feeling developer workspace with a split-pane layout (editor, terminal, live preview) powered by Monaco Editor; managed synchronized file tree and tab state via Zustand with React Query handling optimistic updates for a lag-free editing experience."

achievements:
  - id: achievement.lms
    text: "Sole developer of an internal LMS migration platform at Okanagan College, built and deployed end-to-end and relied on daily by 1,500+ staff and instructors for the institution-wide Moodle-to-Brightspace transition -- featuring guided step-by-step migration workflows with progress tracking and complete records, real-time notifications and chat, and AI-powered templating."
  - id: achievement.stock
    text: "Built an end-to-end stock prediction pipeline covering 500 S\\&P 500 constituents over 5 years of 15-minute bar data -- XGBoost models trained across 26 intraday horizons on 4x NVIDIA H100 GPUs (DRAC), with automated warm-start retraining every 15 minutes during market hours, served via a FastAPI backend backed by a PostgreSQL data warehouse and a multi-rolling feature pipeline."
  - id: achievement.freelancer
    text: "Ranked in the top 2\\% of verified freelancers on Freelancer.com with a 5-star rating, delivering 25+ production-grade projects."
  - id: achievement.hackathon
    text: "Won an inter-university college hackathon, demonstrating innovative problem-solving and technical proficiency."

skills:
  - category: "Languages"
    items: "JavaScript (ES6+), TypeScript, Python, Go (Golang), Bash"
  - category: "Frontend \\& Mobile"
    items: "React, Next.js, React Native, Qwik.js, Electron"
  - category: "Backend \\& Messaging"
    items: "NestJS, FastAPI, Express, Fastify, GraphQL, gRPC/Protobuf, Apache Kafka, BullMQ, RabbitMQ"
  - category: "Databases"
    items: "PostgreSQL, MongoDB, DynamoDB, Redis, MySQL, SurrealDB, SQLite"
  - category: "Cloud \\& DevOps"
    items: "AWS, Azure, Docker, Kubernetes, Terraform, Pulumi, Bazel, Jenkins, GitHub Actions"
  - category: "AI \\& GenAI"
    items: "LangChain, LangSmith, AutoGen, RAG, FAISS, Pinecone, Qdrant, AstraDB, AWS Bedrock"
```

Note: `\%`, `\&`, and `\\` are pre-escaped for LaTeX directly in this file
because this content is author-controlled and rendered as-is (see Task 7) —
this is the one place in the system where LaTeX special characters must be
written correctly by hand, since it is the only free-text content that
isn't run through the runtime `latex_escape()` helper (that helper is
reserved for the LLM-generated summary line — see Task 5/7).

- [ ] **Step 7: Verify the real bank loads**

Run: `uv run python -c "from pathlib import Path; from app.bank import load_bank; b = load_bank(Path('content/resume_bank.yaml')); print(len(b.jobs), len(b.projects), len(b.achievements), len(b.skills))"`
Expected: `4 2 4 6`

- [ ] **Step 8: Commit**

```bash
git add app/bank.py tests/fixtures/sample_bank.yaml tests/test_bank.py content/resume_bank.yaml
git commit -m "resume-tailor-service: add resume content bank schema, loader, and real data"
```

---

### Task 3: API and manifest models

**Files:**
- Create: `resume-tailor-service/app/models.py`
- Test: `resume-tailor-service/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure Pydantic models).
- Produces: `TailorRequest(jd_text: str, company: str, role: str)`, `JobSelection(job_id: str, bullet_ids: list[str])`, `ProjectSelection(project_id: str, bullet_ids: list[str])`, `Manifest(summary: str, job_selections: list[JobSelection], project_selections: list[ProjectSelection], achievement_ids: list[str], job_trim_priority: list[str])`, `TailorResponse(pdf_path: str, manifest: Manifest, pages: int)`. Later tasks (5, 6, 7, 8, 9) import all of these from `app.models`.

- [ ] **Step 1: Write the failing test**

```python
# resume-tailor-service/tests/test_models.py
import pytest
from pydantic import ValidationError
from app.models import Manifest, JobSelection, ProjectSelection, TailorRequest, TailorResponse


def _sample_manifest_kwargs():
    return dict(
        summary="Backend engineer with distributed systems experience.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_manifest_parses_valid_data():
    m = Manifest(**_sample_manifest_kwargs())
    assert m.job_selections[0].job_id == "acme"


def test_manifest_missing_field_raises():
    kwargs = _sample_manifest_kwargs()
    del kwargs["summary"]
    with pytest.raises(ValidationError):
        Manifest(**kwargs)


def test_tailor_request_requires_all_fields():
    req = TailorRequest(jd_text="We need a backend engineer.", company="Acme", role="SWE")
    assert req.company == "Acme"
    with pytest.raises(ValidationError):
        TailorRequest(jd_text="x", company="Acme")


def test_tailor_response_wraps_manifest():
    resp = TailorResponse(pdf_path="/tmp/out.pdf", manifest=Manifest(**_sample_manifest_kwargs()), pages=1)
    assert resp.pages == 1
    assert resp.manifest.achievement_ids == ["achievement.1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Write `app/models.py`**

```python
from pydantic import BaseModel


class TailorRequest(BaseModel):
    jd_text: str
    company: str
    role: str


class JobSelection(BaseModel):
    job_id: str
    bullet_ids: list[str]


class ProjectSelection(BaseModel):
    project_id: str
    bullet_ids: list[str]


class Manifest(BaseModel):
    summary: str
    job_selections: list[JobSelection]
    project_selections: list[ProjectSelection]
    achievement_ids: list[str]
    job_trim_priority: list[str]


class TailorResponse(BaseModel):
    pdf_path: str
    manifest: Manifest
    pages: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "resume-tailor-service: add API and manifest Pydantic models"
```

---

### Task 4: Auth dependency (bearer token)

**Files:**
- Create: `resume-tailor-service/app/auth.py`
- Test: `resume-tailor-service/tests/test_auth.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `verify_token(authorization: str = Header(default="")) -> None` — a FastAPI dependency that raises `HTTPException(401)` on missing/invalid token and `HTTPException(500)` if `RESUME_TAILOR_TOKEN` isn't set. Used by Task 9's `/tailor` route.

- [ ] **Step 1: Write the failing test**

```python
# resume-tailor-service/tests/test_auth.py
import pytest
from fastapi import HTTPException
from app.auth import verify_token


def test_verify_token_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    verify_token(authorization="Bearer secret123")  # should not raise


def test_verify_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Bearer wrong")
    assert exc_info.value.status_code == 401


def test_verify_token_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="")
    assert exc_info.value.status_code == 401


def test_verify_token_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Basic secret123")
    assert exc_info.value.status_code == 401


def test_verify_token_errors_if_unconfigured(monkeypatch):
    monkeypatch.delenv("RESUME_TAILOR_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Bearer anything")
    assert exc_info.value.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Write `app/auth.py`**

```python
import hmac
import os
from fastapi import Header, HTTPException


def verify_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("RESUME_TAILOR_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=500, detail="RESUME_TAILOR_TOKEN not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid or missing token")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth.py
git commit -m "resume-tailor-service: add bearer-token auth dependency"
```

---

### Task 5: Manifest validation (the anti-fabrication guardrail)

**Files:**
- Create: `resume-tailor-service/app/errors.py`
- Create: `resume-tailor-service/app/validate.py`
- Test: `resume-tailor-service/tests/test_validate.py`

**Interfaces:**
- Consumes: `ResumeBank`, `all_job_ids`, `all_project_ids`, `all_achievement_ids`, `all_job_bullet_ids`, `all_project_bullet_ids`, `bank_text_blob` from `app.bank` (Task 2); `Manifest` from `app.models` (Task 3).
- Produces: `app/errors.py`: `TailorValidationError(Exception)`, `PdfCompileError(Exception)`, `CannotFitOnePageError(Exception)` (all three used across Tasks 6, 8, 9). `app/validate.py`: `validate_manifest(manifest: Manifest, bank: ResumeBank) -> list[str]` (empty list = valid) and `extract_facts(text: str) -> set[str]`, used by Task 6.

- [ ] **Step 1: Write the failing test**

```python
# resume-tailor-service/tests/test_validate.py
from pathlib import Path
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.validate import validate_manifest, extract_facts

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"


def _valid_manifest():
    return Manifest(
        summary="Engineer who cut latency 40 percent on a 500 widget/hour pipeline.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1", "acme.bullet.2"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_valid_manifest_has_no_errors():
    bank = load_bank(FIXTURE)
    assert validate_manifest(_valid_manifest(), bank) == []


def test_unknown_job_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].job_id = "does-not-exist"
    errors = validate_manifest(m, bank)
    assert any("does-not-exist" in e for e in errors)


def test_unknown_bullet_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].bullet_ids.append("acme.bullet.99")
    errors = validate_manifest(m, bank)
    assert any("acme.bullet.99" in e for e in errors)


def test_bullet_id_from_wrong_job_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_selections[0].bullet_ids = ["project.widgetizer.bullet.1"]
    errors = validate_manifest(m, bank)
    assert len(errors) >= 1


def test_unknown_project_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.project_selections[0].project_id = "ghost-project"
    errors = validate_manifest(m, bank)
    assert any("ghost-project" in e for e in errors)


def test_unknown_achievement_id_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.achievement_ids = ["achievement.does-not-exist"]
    errors = validate_manifest(m, bank)
    assert any("achievement.does-not-exist" in e for e in errors)


def test_job_trim_priority_must_match_job_ids_exactly():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.job_trim_priority = ["acme", "phantom-job"]
    errors = validate_manifest(m, bank)
    assert any("job_trim_priority" in e for e in errors)


def test_summary_with_untraceable_number_is_rejected():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.summary = "Cut costs by 999 percent using a proprietary framework."
    errors = validate_manifest(m, bank)
    assert any("999" in e for e in errors)


def test_summary_with_traceable_facts_passes():
    bank = load_bank(FIXTURE)
    m = _valid_manifest()
    m.summary = "Built a 500 widget per hour pipeline, cutting latency 40 percent."
    assert validate_manifest(m, bank) == []


def test_extract_facts_finds_numbers_and_acronyms():
    facts = extract_facts("Cut costs by 40% using AWS and 12K+ users on a RAG pipeline.")
    assert "40%" in facts
    assert "12K+" in facts
    assert "AWS" in facts
    assert "RAG" in facts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.validate'`

- [ ] **Step 3: Write `app/errors.py`**

```python
class TailorValidationError(Exception):
    """Raised when the model's manifest fails validation against the resume bank."""


class PdfCompileError(Exception):
    """Raised when pdflatex fails to produce a PDF."""


class CannotFitOnePageError(Exception):
    """Raised when the resume still exceeds one page after exhausting all trims."""
```

- [ ] **Step 4: Write `app/validate.py`**

```python
import re
from app.bank import (
    ResumeBank, all_job_ids, all_project_ids, all_achievement_ids,
    all_job_bullet_ids, all_project_bullet_ids, bank_text_blob,
)
from app.models import Manifest

_NUMERIC_RE = re.compile(r"\d[\d,.]*\+?%?[KkMmBb]?\+?")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")


def extract_facts(text: str) -> set[str]:
    return set(_NUMERIC_RE.findall(text)) | set(_ACRONYM_RE.findall(text))


def validate_manifest(manifest: Manifest, bank: ResumeBank) -> list[str]:
    errors: list[str] = []

    job_ids = all_job_ids(bank)
    project_ids = all_project_ids(bank)
    achievement_ids = all_achievement_ids(bank)
    job_bullet_ids = all_job_bullet_ids(bank)
    project_bullet_ids = all_project_bullet_ids(bank)

    for js in manifest.job_selections:
        if js.job_id not in job_ids:
            errors.append(f"unknown job_id: {js.job_id}")
            continue
        valid_bullets = job_bullet_ids[js.job_id]
        for bid in js.bullet_ids:
            if bid not in valid_bullets:
                errors.append(f"unknown bullet_id {bid!r} for job {js.job_id!r}")

    for ps in manifest.project_selections:
        if ps.project_id not in project_ids:
            errors.append(f"unknown project_id: {ps.project_id}")
            continue
        valid_bullets = project_bullet_ids[ps.project_id]
        for bid in ps.bullet_ids:
            if bid not in valid_bullets:
                errors.append(f"unknown bullet_id {bid!r} for project {ps.project_id!r}")

    for aid in manifest.achievement_ids:
        if aid not in achievement_ids:
            errors.append(f"unknown achievement_id: {aid}")

    if set(manifest.job_trim_priority) != job_ids:
        errors.append(
            f"job_trim_priority must be exactly {sorted(job_ids)}, got {manifest.job_trim_priority}"
        )

    blob = bank_text_blob(bank)
    for fact in extract_facts(manifest.summary):
        if fact not in blob:
            errors.append(f"untraceable fact in summary: {fact!r}")

    return errors
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_validate.py -v`
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add app/errors.py app/validate.py tests/test_validate.py
git commit -m "resume-tailor-service: add manifest validation (anti-fabrication guardrail)"
```

---

### Task 6: Anthropic call orchestration (prompt, parse, validate, retry)

**Files:**
- Create: `resume-tailor-service/app/tailor.py`
- Test: `resume-tailor-service/tests/test_tailor.py`

**Interfaces:**
- Consumes: `ResumeBank` (Task 2), `Manifest` (Task 3), `validate_manifest` (Task 5), `TailorValidationError` (Task 5).
- Produces: `build_prompt(jd_text, company, role, bank, previous_errors=None) -> str`, `parse_manifest_json(raw_text: str) -> dict`, `get_manifest(jd_text, company, role, bank, client, max_retries=1) -> Manifest`. `get_manifest` is called by Task 9's `/tailor` route with a real `anthropic.Anthropic()` client.

- [ ] **Step 1: Write the failing test**

```python
# resume-tailor-service/tests/test_tailor.py
import json
from pathlib import Path
import pytest
from app.bank import load_bank
from app.errors import TailorValidationError
from app.tailor import build_prompt, parse_manifest_json, get_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"

VALID_MANIFEST_DICT = {
    "summary": "Built a 500 widget per hour pipeline, cutting latency 40 percent.",
    "job_selections": [{"job_id": "acme", "bullet_ids": ["acme.bullet.1", "acme.bullet.2"]}],
    "project_selections": [
        {"project_id": "widgetizer", "bullet_ids": ["project.widgetizer.bullet.1"]}
    ],
    "achievement_ids": ["achievement.1"],
    "job_trim_priority": ["acme"],
}

INVALID_MANIFEST_DICT = {**VALID_MANIFEST_DICT, "job_selections": [{"job_id": "ghost", "bullet_ids": []}]}


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [type("Block", (), {"text": text})()]


class _FakeMessages:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        text = self._responses[self.calls]
        self.calls += 1
        return _FakeMessage(text)


class _FakeClient:
    def __init__(self, responses: list[str]):
        self.messages = _FakeMessages(responses)


def test_build_prompt_includes_jd_and_bank_ids():
    bank = load_bank(FIXTURE)
    prompt = build_prompt("We need a backend engineer.", "Acme", "SWE", bank)
    assert "We need a backend engineer." in prompt
    assert "acme.bullet.1" in prompt
    assert "project.widgetizer.bullet.1" in prompt
    assert "achievement.1" in prompt


def test_parse_manifest_json_handles_plain_json():
    parsed = parse_manifest_json(json.dumps(VALID_MANIFEST_DICT))
    assert parsed["summary"] == VALID_MANIFEST_DICT["summary"]


def test_parse_manifest_json_handles_fenced_json():
    fenced = "```json\n" + json.dumps(VALID_MANIFEST_DICT) + "\n```"
    parsed = parse_manifest_json(fenced)
    assert parsed["job_selections"][0]["job_id"] == "acme"


def test_get_manifest_succeeds_on_first_valid_response():
    bank = load_bank(FIXTURE)
    client = _FakeClient([json.dumps(VALID_MANIFEST_DICT)])
    manifest = get_manifest("jd text", "Acme", "SWE", bank, client)
    assert manifest.job_selections[0].job_id == "acme"
    assert client.messages.calls == 1


def test_get_manifest_retries_once_then_succeeds():
    bank = load_bank(FIXTURE)
    client = _FakeClient([json.dumps(INVALID_MANIFEST_DICT), json.dumps(VALID_MANIFEST_DICT)])
    manifest = get_manifest("jd text", "Acme", "SWE", bank, client, max_retries=1)
    assert manifest.job_selections[0].job_id == "acme"
    assert client.messages.calls == 2


def test_get_manifest_raises_after_exhausting_retries():
    bank = load_bank(FIXTURE)
    client = _FakeClient([json.dumps(INVALID_MANIFEST_DICT), json.dumps(INVALID_MANIFEST_DICT)])
    with pytest.raises(TailorValidationError):
        get_manifest("jd text", "Acme", "SWE", bank, client, max_retries=1)
    assert client.messages.calls == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tailor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tailor'`

- [ ] **Step 3: Write `app/tailor.py`**

```python
import json
from app.bank import ResumeBank
from app.errors import TailorValidationError
from app.models import Manifest
from app.validate import validate_manifest

MODEL_NAME = "claude-sonnet-5"


def _describe_bank(bank: ResumeBank) -> str:
    lines: list[str] = []
    for job in bank.jobs:
        lines.append(f"JOB {job.id} ({job.company}, {job.title}, {job.dates}):")
        for b in job.bullets:
            lines.append(f"  - {b.id}: {b.text}")
    for proj in bank.projects:
        lines.append(f"PROJECT {proj.id} ({proj.name}):")
        for b in proj.bullets:
            lines.append(f"  - {b.id}: {b.text}")
    lines.append("ACHIEVEMENTS:")
    for b in bank.achievements:
        lines.append(f"  - {b.id}: {b.text}")
    return "\n".join(lines)


def build_prompt(jd_text: str, company: str, role: str, bank: ResumeBank, previous_errors: list[str] | None = None) -> str:
    correction = ""
    if previous_errors:
        correction = (
            "\nYour previous response was invalid for these reasons:\n"
            + "\n".join(f"- {e}" for e in previous_errors)
            + "\nFix these and respond again, following the rules exactly.\n"
        )
    job_ids = sorted({job.id for job in bank.jobs})
    return f"""You are selecting content for a resume tailored to a specific job.
Company: {company}
Role: {role}
Job description:
{jd_text}

Below is the ONLY resume content that exists. You may only reference these
exact IDs. You may NOT invent new bullet text, new IDs, or new facts.

{_describe_bank(bank)}
{correction}
Respond with ONLY a JSON object (no prose, no markdown fences) matching this shape:
{{
  "summary": "1-2 sentence summary using ONLY facts/numbers that appear above",
  "job_selections": [{{"job_id": "<one of {job_ids}>", "bullet_ids": ["<ids from that job, most relevant first>"]}}, ... one entry per job, every job must appear],
  "project_selections": [{{"project_id": "<project id>", "bullet_ids": ["<ids from that project>"]}}, ... most relevant project first],
  "achievement_ids": ["<achievement ids, most relevant first>"],
  "job_trim_priority": ["<all job ids, ordered least-relevant to most-relevant to this JD>"]
}}"""


def parse_manifest_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[len("json"):].strip()
    return json.loads(text)


def get_manifest(jd_text: str, company: str, role: str, bank: ResumeBank, client, max_retries: int = 1) -> Manifest:
    previous_errors: list[str] | None = None
    attempts = max_retries + 1
    for attempt in range(attempts):
        prompt = build_prompt(jd_text, company, role, bank, previous_errors)
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text
        parsed = parse_manifest_json(raw_text)
        manifest = Manifest.model_validate(parsed)
        errors = validate_manifest(manifest, bank)
        if not errors:
            return manifest
        previous_errors = errors
    raise TailorValidationError(f"manifest invalid after {attempts} attempt(s): {previous_errors}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tailor.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/tailor.py tests/test_tailor.py
git commit -m "resume-tailor-service: add Anthropic manifest orchestration with validate+retry"
```

---

### Task 7: Jinja2 template and rendering

**Files:**
- Create: `resume-tailor-service/templates/resume_template.tex.jinja`
- Create: `resume-tailor-service/app/render_tex.py`
- Test: `resume-tailor-service/tests/test_render_tex.py`

**Interfaces:**
- Consumes: `ResumeBank` (Task 2), `Manifest` (Task 3).
- Produces: `latex_escape(text: str) -> str`, `render_tex(manifest: Manifest, bank: ResumeBank, template_dir: Path) -> str`. Used by Task 8's `render_and_fit`.

- [ ] **Step 1: Write the Jinja2 template**

Uses non-default delimiters (`((* *))`, `((( )))`) so Jinja2 syntax never
collides with LaTeX's own `{`, `}`, `\` characters.

```latex
% resume-tailor-service/templates/resume_template.tex.jinja
\documentclass{resume}
\name{(((contact.name)))}
\address{(((contact.phone))) $|$ (((contact.location)))}
\address{\href{mailto:(((contact.email)))}{(((contact.email)))} $|$ \href{(((contact.linkedin_url)))}{LinkedIn} $|$ \href{(((contact.github_url)))}{GitHub} $|$ \href{(((contact.website_url)))}{(((contact.website_display)))}}

\begin{document}

\begin{rSection}{Summary}
(((summary)))
\end{rSection}

\begin{rSection}{Education}
\textbf{(((education.degree)))}, (((education.school))) \hfill (((education.date)))
\end{rSection}

\begin{rSection}{Experience}
((* for job in jobs *))
\begin{rSubsection}{(((job.company)))}{(((job.dates)))}{(((job.title)))}{(((job.location)))}
((* for bullet in job.bullets *))
\item (((bullet)))
((* endfor *))
\end{rSubsection}
((* endfor *))
\end{rSection}

\begin{rSection}{Projects}
((* for project in projects *))
\textbf{(((project.name)))} \hfill \textit{(((project.tech)))}
\begin{list}{$\cdot$}{\leftmargin=1em}
((* for bullet in project.bullets *))
\item (((bullet)))
((* endfor *))
\end{list}
((* endfor *))
\end{rSection}

\begin{rSection}{Technical Skills}
\begin{tabular}{@{}ll@{}}
((* for line in skills *))
\textbf{(((line.category)))} & (((line.items))) \\
((* endfor *))
\end{tabular}
\end{rSection}

\begin{rSection}{Achievements}
\begin{list}{$\cdot$}{\leftmargin=1em}
((* for bullet in achievements *))
\item (((bullet)))
((* endfor *))
\end{list}
\end{rSection}

\end{document}
```

- [ ] **Step 2: Write the failing test**

```python
# resume-tailor-service/tests/test_render_tex.py
from pathlib import Path
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.render_tex import render_tex, latex_escape

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _manifest():
    return Manifest(
        summary="Backend engineer, 500 widgets/hour.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_render_tex_includes_selected_content():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "Test Person" in tex
    assert "Built a widget pipeline processing 500 widgets per hour." in tex
    assert "Widgetizer" in tex
    assert "Won the regional Test Hackathon." in tex


def test_render_tex_excludes_unselected_bullets():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "Reduced widget latency by 40 percent." not in tex


def test_render_tex_jobs_stay_in_chronological_bank_order():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert tex.index("Acme Corp") < tex.index("Achievements")


def test_latex_escape_handles_special_characters():
    assert latex_escape("50% & growing_fast #1") == r"50\% \& growing\_fast \#1"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_render_tex.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.render_tex'`

- [ ] **Step 4: Write `app/render_tex.py`**

```python
from pathlib import Path
import jinja2
from app.bank import ResumeBank
from app.models import Manifest

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_SPECIAL.get(ch, ch) for ch in text)


def _build_context(manifest: Manifest, bank: ResumeBank) -> dict:
    job_sel_by_id = {js.job_id: js for js in manifest.job_selections}
    jobs_ctx = []
    for job in bank.jobs:
        sel = job_sel_by_id.get(job.id)
        if sel is None:
            continue
        bullet_text = {b.id: b.text for b in job.bullets}
        jobs_ctx.append({
            "company": job.company,
            "location": job.location,
            "title": job.title,
            "dates": job.dates,
            "bullets": [bullet_text[bid] for bid in sel.bullet_ids],
        })

    project_by_id = {p.id: p for p in bank.projects}
    projects_ctx = []
    for ps in manifest.project_selections:
        proj = project_by_id[ps.project_id]
        bullet_text = {b.id: b.text for b in proj.bullets}
        projects_ctx.append({
            "name": proj.name,
            "tech": proj.tech,
            "bullets": [bullet_text[bid] for bid in ps.bullet_ids],
        })

    achievement_text = {b.id: b.text for b in bank.achievements}
    achievements_ctx = [achievement_text[aid] for aid in manifest.achievement_ids]

    return {
        "contact": bank.contact.model_dump(),
        "education": bank.education.model_dump(),
        "summary": latex_escape(manifest.summary),
        "jobs": jobs_ctx,
        "projects": projects_ctx,
        "achievements": achievements_ctx,
        "skills": [s.model_dump() for s in bank.skills],
    }


def render_tex(manifest: Manifest, bank: ResumeBank, template_dir: Path) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    template = env.get_template("resume_template.tex.jinja")
    return template.render(**_build_context(manifest, bank))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_render_tex.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/resume_template.tex.jinja app/render_tex.py tests/test_render_tex.py
git commit -m "resume-tailor-service: add Jinja2 LaTeX template and renderer"
```

---

### Task 8: PDF compile, page count, and the one-page trim loop

**Files:**
- Create: `resume-tailor-service/app/render.py`
- Test: `resume-tailor-service/tests/test_render.py`

**Interfaces:**
- Consumes: `render_tex`, `Manifest`, `ResumeBank` (Tasks 2, 3, 7), `PdfCompileError`, `CannotFitOnePageError` (Task 5).
- Produces: `compile_pdf(tex_source: str, work_dir: Path, cls_path: Path) -> Path`, `count_pages(pdf_path: Path) -> int`, `trim_one_item(manifest: Manifest) -> Manifest | None`, `render_and_fit(manifest: Manifest, bank: ResumeBank, template_dir: Path, cls_path: Path, work_dir: Path, max_trim_attempts: int = 6) -> tuple[Path, Manifest, int]`. Used directly by Task 9's `/tailor` route.

- [ ] **Step 1: Write the failing test**

This test requires `pdflatex` on `PATH` (already confirmed installed at
`/Library/TeX/texbin/pdflatex` on this machine) — it is skipped automatically
if missing, so it stays portable to CI/VPS environments without LaTeX.

```python
# resume-tailor-service/tests/test_render.py
import shutil
from pathlib import Path
import pytest
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.render_tex import render_tex
from app.render import compile_pdf, count_pages, trim_one_item, render_and_fit
from app.errors import PdfCompileError, CannotFitOnePageError

pytestmark = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"


def _manifest():
    return Manifest(
        summary="Backend engineer, 500 widgets/hour.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_compile_pdf_produces_a_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    pdf_path = compile_pdf(tex, tmp_path, CLS_PATH)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"


def test_compile_pdf_raises_on_broken_tex(tmp_path):
    with pytest.raises(PdfCompileError):
        compile_pdf(r"\documentclass{resume}\begin{document}\badcommand\end{document}", tmp_path, CLS_PATH)


def test_count_pages_on_real_compiled_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    pdf_path = compile_pdf(tex, tmp_path, CLS_PATH)
    assert count_pages(pdf_path) == 1


def test_trim_one_item_drops_last_project_first():
    m = _manifest()
    m.project_selections.append(
        ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
    )
    trimmed = trim_one_item(m)
    assert len(trimmed.project_selections) == 1


def test_trim_one_item_then_drops_achievement():
    m = _manifest()
    m.project_selections = []
    trimmed = trim_one_item(m)
    assert trimmed.achievement_ids == []


def test_trim_one_item_then_drops_lowest_priority_job_bullet():
    m = _manifest()
    m.project_selections = []
    m.achievement_ids = []
    m.job_selections = [JobSelection(job_id="acme", bullet_ids=["acme.bullet.1", "acme.bullet.2"])]
    trimmed = trim_one_item(m)
    assert trimmed.job_selections[0].bullet_ids == ["acme.bullet.1"]


def test_trim_one_item_returns_none_when_nothing_left():
    m = _manifest()
    m.project_selections = []
    m.achievement_ids = []
    m.job_selections = [JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])]
    assert trim_one_item(m) is None


def test_render_and_fit_returns_one_page_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    pdf_path, final_manifest, pages = render_and_fit(_manifest(), bank, TEMPLATE_DIR, CLS_PATH, tmp_path)
    assert pages == 1
    assert pdf_path.exists()


def test_render_and_fit_raises_when_it_cannot_fit(tmp_path, monkeypatch):
    bank = load_bank(FIXTURE)
    monkeypatch.setattr("app.render.count_pages", lambda _pdf_path: 2)
    with pytest.raises(CannotFitOnePageError):
        render_and_fit(_manifest(), bank, TEMPLATE_DIR, CLS_PATH, tmp_path, max_trim_attempts=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.render'`

- [ ] **Step 3: Write `app/render.py`**

```python
import shutil
import subprocess
from pathlib import Path
import pypdf
from app.bank import ResumeBank
from app.models import Manifest
from app.render_tex import render_tex
from app.errors import PdfCompileError, CannotFitOnePageError


def compile_pdf(tex_source: str, work_dir: Path, cls_path: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(cls_path, work_dir / "resume.cls")
    tex_file = work_dir / "resume.tex"
    tex_file.write_text(tex_source)

    result = None
    for _ in range(2):  # twice so hyperref cross-references settle
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_file.name],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

    pdf_path = work_dir / "resume.pdf"
    if not pdf_path.exists():
        log_path = work_dir / "resume.log"
        tail = log_path.read_text()[-2000:] if log_path.exists() else (result.stdout[-2000:] if result else "")
        raise PdfCompileError(tail)
    return pdf_path


def count_pages(pdf_path: Path) -> int:
    reader = pypdf.PdfReader(str(pdf_path))
    return len(reader.pages)


def trim_one_item(manifest: Manifest) -> Manifest | None:
    m = manifest.model_copy(deep=True)

    if m.project_selections:
        m.project_selections.pop()
        return m

    if m.achievement_ids:
        m.achievement_ids.pop()
        return m

    for job_id in m.job_trim_priority:
        for js in m.job_selections:
            if js.job_id == job_id and len(js.bullet_ids) > 1:
                js.bullet_ids.pop()
                return m

    return None


def render_and_fit(
    manifest: Manifest,
    bank: ResumeBank,
    template_dir: Path,
    cls_path: Path,
    work_dir: Path,
    max_trim_attempts: int = 6,
) -> tuple[Path, Manifest, int]:
    current = manifest
    for _ in range(max_trim_attempts + 1):
        tex_source = render_tex(current, bank, template_dir)
        pdf_path = compile_pdf(tex_source, work_dir, cls_path)
        pages = count_pages(pdf_path)
        if pages <= 1:
            return pdf_path, current, pages
        trimmed = trim_one_item(current)
        if trimmed is None:
            break
        current = trimmed
    raise CannotFitOnePageError(
        f"could not fit resume to one page after {max_trim_attempts} trim attempts"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render.py -v`
Expected: 9 passed (or 9 skipped if `pdflatex` is unavailable in the environment running the tests).

- [ ] **Step 5: Commit**

```bash
git add app/render.py tests/test_render.py
git commit -m "resume-tailor-service: add pdflatex compile, page count, and one-page trim loop"
```

---

### Task 9: FastAPI app wiring (`/tailor`, `/health`)

**Files:**
- Create: `resume-tailor-service/app/main.py`
- Test: `resume-tailor-service/tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 2–8: `app.bank.load_bank`, `app.auth.verify_token`, `app.models.{TailorRequest, TailorResponse}`, `app.errors.{TailorValidationError, PdfCompileError, CannotFitOnePageError}`, and the `app.tailor` / `app.render` modules (imported and called through the module object, not `from`-imported, so tests can monkeypatch them).
- Produces: `app` (the FastAPI instance) — this is what `uvicorn app.main:app` serves, and what Task 10's Dockerfile CMD runs.

- [ ] **Step 1: Write the failing test**

```python
# resume-tailor-service/tests/test_main.py
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app.main as main_module
from app.models import Manifest, JobSelection, ProjectSelection
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError


def _fake_manifest():
    return Manifest(
        summary="Backend engineer.",
        job_selections=[JobSelection(job_id="ommuse", bullet_ids=["ommuse.bullet.1"])],
        project_selections=[ProjectSelection(project_id="docintel", bullet_ids=["project.docintel.bullet.1"])],
        achievement_ids=["achievement.lms"],
        job_trim_priority=["ommuse", "morethinks", "bwisher", "jythu"],
    )


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "test-token")


def test_health_requires_no_auth():
    client = TestClient(main_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tailor_rejects_missing_token():
    client = TestClient(main_module.app)
    resp = client.post("/tailor", json={"jd_text": "x", "company": "Acme", "role": "SWE"})
    assert resp.status_code == 401


def test_tailor_success_returns_pdf_path_and_manifest(monkeypatch, tmp_path):
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())
    monkeypatch.setattr(main_module.render, "render_and_fit", lambda *a, **k: (fake_pdf, _fake_manifest(), 1))

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "We need a backend engineer.", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pages"] == 1
    assert body["pdf_path"] == str(fake_pdf)
    assert body["manifest"]["job_selections"][0]["job_id"] == "ommuse"


def test_tailor_returns_502_on_validation_failure(monkeypatch):
    def _raise(*a, **k):
        raise TailorValidationError("bad manifest")
    monkeypatch.setattr(main_module.tailor, "get_manifest", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 502


def test_tailor_returns_422_when_cannot_fit_one_page(monkeypatch):
    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())

    def _raise(*a, **k):
        raise CannotFitOnePageError("nope")
    monkeypatch.setattr(main_module.render, "render_and_fit", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 422


def test_tailor_returns_500_on_compile_failure(monkeypatch):
    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())

    def _raise(*a, **k):
        raise PdfCompileError("log tail")
    monkeypatch.setattr(main_module.render, "render_and_fit", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write `app/main.py`**

```python
import uuid
from pathlib import Path
import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException

from app import tailor, render
from app.auth import verify_token
from app.bank import load_bank
from app.models import TailorRequest, TailorResponse
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
TEMPLATE_DIR = BASE_DIR / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"
OUTPUT_DIR = BASE_DIR / "output"

app = FastAPI(title="resume-tailor-service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tailor", response_model=TailorResponse)
def tailor_resume(req: TailorRequest, _auth: None = Depends(verify_token)):
    bank = load_bank(BANK_PATH)
    client = anthropic.Anthropic()

    try:
        manifest = tailor.get_manifest(req.jd_text, req.company, req.role, bank, client)
    except TailorValidationError as e:
        raise HTTPException(status_code=502, detail=f"model produced an invalid manifest: {e}")

    slug = f"{req.company}-{req.role}".lower().replace(" ", "-")
    work_dir = OUTPUT_DIR / f"{slug}-{uuid.uuid4().hex[:8]}"

    try:
        pdf_path, final_manifest, pages = render.render_and_fit(
            manifest, bank, TEMPLATE_DIR, CLS_PATH, work_dir
        )
    except PdfCompileError as e:
        raise HTTPException(status_code=500, detail=f"LaTeX compile failed: {e}")
    except CannotFitOnePageError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return TailorResponse(pdf_path=str(pdf_path), manifest=final_manifest, pages=pages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_main.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests across every task pass (or the `pdflatex`-dependent tests
in `test_render.py` show as skipped if run somewhere without LaTeX).

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "resume-tailor-service: wire up FastAPI app with /tailor and /health"
```

---

### Task 10: Dockerfile and docker-compose for VPS deployment

**Files:**
- Create: `resume-tailor-service/Dockerfile`
- Create: `resume-tailor-service/docker-compose.yml`
- Create: `resume-tailor-service/.dockerignore`

**Interfaces:**
- Consumes: the full `app/`, `content/`, `templates/`, `pyproject.toml`, `uv.lock` produced by Tasks 1–9.
- Produces: a container image exposing port `8420`, running `uvicorn app.main:app`.

- [ ] **Step 1: Write `.dockerignore`**

```
.venv/
__pycache__/
*.pyc
output/
.env
tests/
uv.lock.bak
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /srv/app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY content ./content
COPY templates ./templates

RUN mkdir -p /srv/app/output

EXPOSE 8420

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  resume-tailor:
    build: .
    ports:
      - "8420:8420"
    env_file:
      - .env
    volumes:
      - ./output:/srv/app/output
    restart: unless-stopped
```

- [ ] **Step 4: Build the image**

Run (from `resume-tailor-service/`, with a real `.env` created from
`.env.example` first — required because the image build itself doesn't need
secrets, but `docker compose up` below does):
`docker build -t resume-tailor-service .`
Expected: build completes with exit code 0.

- [ ] **Step 5: Run the container and verify health**

```bash
cp .env.example .env   # then fill in real ANTHROPIC_API_KEY and RESUME_TAILOR_TOKEN
docker compose up -d
curl -s http://localhost:8420/health
```
Expected: `{"status":"ok"}`. Then `docker compose down` when done checking.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "resume-tailor-service: add Docker packaging for VPS deployment"
```

---

### Task 11: Smoke test script (real end-to-end check)

**Files:**
- Create: `resume-tailor-service/scripts/smoke_test.py`

**Interfaces:**
- Consumes: a running instance of the service (local or VPS) and a real `RESUME_TAILOR_TOKEN`.
- Produces: a pass/fail console report; not part of the pytest suite (it needs a live server plus a real Anthropic API key, so it stays a manual/integration check, not CI).

- [ ] **Step 1: Write `scripts/smoke_test.py`**

```python
import os
import sys
import httpx

SAMPLE_JDS = [
    ("Acme Cloud", "Backend Engineer",
     "We're looking for a backend engineer with experience in distributed "
     "systems, message queues, Go or Python, and cloud infrastructure (AWS "
     "or GCP). You'll own service reliability and CI/CD."),
    ("Vectra AI", "AI/ML Engineer",
     "Seeking an engineer to build RAG pipelines, work with vector "
     "databases, and integrate LLM providers with failover. Python and "
     "LangChain experience required."),
    ("Ridewell", "Mobile Engineer",
     "Build and maintain our React Native rider app serving thousands of "
     "users, including native module work and CI/CD for app store "
     "releases."),
]


def main() -> int:
    base_url = os.environ.get("RESUME_TAILOR_URL", "http://localhost:8420")
    token = os.environ["RESUME_TAILOR_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    failures = []
    for company, role, jd_text in SAMPLE_JDS:
        resp = httpx.post(
            f"{base_url}/tailor",
            headers=headers,
            json={"jd_text": jd_text, "company": company, "role": role},
            timeout=60,
        )
        if resp.status_code != 200:
            failures.append(f"{company}/{role}: HTTP {resp.status_code} {resp.text}")
            continue
        body = resp.json()
        if body["pages"] != 1:
            failures.append(f"{company}/{role}: expected 1 page, got {body['pages']}")
        print(f"OK  {company}/{role} -> {body['pdf_path']} ({body['pages']} page)")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nAll {len(SAMPLE_JDS)} sample job descriptions produced valid one-page resumes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against a live local instance**

```bash
uv run uvicorn app.main:app --port 8420 &
RESUME_TAILOR_TOKEN=<your real token from .env> uv run python scripts/smoke_test.py
```
Expected: `All 3 sample job descriptions produced valid one-page resumes.` and
exit code 0. Stop the background server afterward (`kill %1` or `fg` + Ctrl-C).

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "resume-tailor-service: add end-to-end smoke test script"
```

---

### Task 12: Integrate into the job-machine workflow

**Files:**
- Modify: `prompts/wellfound-run.md`
- Modify: `prompts/linkedin-run.md`
- Create: `resume-tailor-service/README.md`
- Modify: `README.md` (repo root)

**Interfaces:**
- Consumes: the running `/tailor` endpoint from Task 9/10.
- Produces: updated run prompts that call the service before every resume upload.

- [ ] **Step 1: Write `resume-tailor-service/README.md`**

```markdown
# resume-tailor-service

Local/VPS service that tailors `resume.pdf` per job description by
selecting and reordering real content from `content/resume_bank.yaml` —
never fabricating — and compiling a guaranteed one-page PDF with your real
`resume.cls`.

## Setup

```bash
cd resume-tailor-service
uv sync
cp .env.example .env   # then fill in ANTHROPIC_API_KEY and RESUME_TAILOR_TOKEN
```

## Run locally

```bash
uv run uvicorn app.main:app --port 8420
```

## Run via Docker (for VPS deployment)

```bash
docker compose up -d
```

## Call it

```bash
curl -s -X POST http://localhost:8420/tailor \
  -H "Authorization: Bearer $RESUME_TAILOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jd_text": "...", "company": "Acme", "role": "Backend Engineer"}'
```

Returns `{"pdf_path": "...", "manifest": {...}, "pages": 1}`.
```

- [ ] **Step 2: Add a resume-tailoring step to `prompts/wellfound-run.md`**

In the numbered steps, change step 3's resume line from `Resume = ./resume.pdf.`
to:

```markdown
3. Per listing: read the job + the company's Wellfound profile. Score fit 1–10.
   - < 6: skip, one-line reason.
   - ≥ 6: apply. Before uploading, call the resume-tailor-service:
     `curl -s -X POST http://localhost:8420/tailor -H "Authorization: Bearer $RESUME_TAILOR_TOKEN" -H "Content-Type: application/json" -d '{"jd_text": "<listing JD text>", "company": "<company>", "role": "<role>"}'`
     and use the returned `pdf_path` for the resume upload. If the service
     isn't running or errors, fall back to `./resume.pdf` and note the
     fallback in the session summary. Custom note per rule 4 in CLAUDE.md.
```

- [ ] **Step 3: Apply the same change to `prompts/linkedin-run.md`**

Read the file first to match its exact current resume-upload line, then
apply the equivalent edit (call `/tailor` before upload, fall back to
`./resume.pdf` on error, note the fallback).

- [ ] **Step 4: Add a setup section to the repo root `README.md`**

Insert a new numbered section after the existing Playwright MCP setup
(section 2) and before "One-time login run", introducing
`resume-tailor-service/` setup as one more one-time step, linking to
`resume-tailor-service/README.md` for details, and noting that
`RESUME_TAILOR_TOKEN` must be exported in the shell running `claude` (or
sourced from `resume-tailor-service/.env`) for the `curl` calls in the run
prompts to authenticate.

- [ ] **Step 5: Manually verify the fallback path**

With the service NOT running, dry-run the new step 3 logic by hand: confirm
`curl` fails fast (connection refused) rather than hanging, so the
"fall back to `./resume.pdf`" behavior is actually reachable in practice.

Run: `curl -s --max-time 5 -X POST http://localhost:8420/tailor -d '{}'`
Expected: connection error within ~5s (not a long hang), confirming the run
prompt's fallback instruction is safe to rely on.

- [ ] **Step 6: Commit**

```bash
git add prompts/wellfound-run.md prompts/linkedin-run.md resume-tailor-service/README.md README.md
git commit -m "job-machine: integrate resume-tailor-service into wellfound/linkedin run prompts"
```

---

## Plan self-review notes

- **Spec coverage:** Deployment targets (Task 10), auth (Task 4), content
  bank (Task 2), manifest+validation (Tasks 3, 5), Anthropic orchestration
  (Task 6), template/render/trim (Tasks 7, 8), API wiring (Task 9), testing
  (Tasks 2–9 unit tests + Task 11 smoke test), workflow integration
  (Task 12) — every section of the design spec maps to at least one task.
- **Consistency check performed:** `Manifest`/`JobSelection`/`ProjectSelection`
  field names are identical across Tasks 3, 5, 6, 7, 8, 9 (`job_id`,
  `bullet_ids`, `project_id`, `achievement_ids`, `job_trim_priority`,
  `summary`) — no renames between tasks.
- **Known follow-up (not a blocking placeholder):** the real
  `content/resume_bank.yaml` bullets in Task 2 are transcribed verbatim but
  without the inline `\textbf{}` emphasis the original `resume.pdf` uses on
  technology keywords. The file is plain, human-editable YAML — adding
  `\textbf{...}` around specific terms later is a content edit, not a code
  change, and doesn't require touching any task in this plan.
