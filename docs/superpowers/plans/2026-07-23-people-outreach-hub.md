# People / Outreach Hub + Local-Only Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a central, editable People/Outreach hub to the dashboard (people with LinkedIn + extra links, outreach status, saved message, optional job tie), and simplify the service to local-only (no auth) with a single start script.

**Architecture:** Three ordered workstreams in one plan. (1) Strip the bearer token from backend, frontend, and tests — the `127.0.0.1` bind is the only boundary. (2) Promote the mock sheet server into the repo and add `scripts/start.sh` that boots mock + API and tears both down. (3) People hub: a JSON-file store (`data/people.json`) behind authless `/api/people` CRUD, a new "People" view in the SPA, and a "People at {company}" section in the inspector, joined to jobs by company.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, `uv`, pytest; Vite + React + TypeScript + Tailwind + lucide-react (built to `app/static/`).

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-07-23-people-outreach-hub-design.md`.
- **No auth anywhere** after Task 1. Security boundary = `--host 127.0.0.1`.
- **Applications stay read-only + sheet-backed.** Only *people* are writable.
- Reuse `app/slug.py::safe_slug` and the `dashboard.py::_resolve_dir` id-guard style (`_ID_RE = ^[A-Za-z0-9._-]+$`, reject `..`). Do not rewrite them.
- Person status vocabulary is exactly: `to-reach | queued | sent | replied | skip` (default `to-reach`).
- Built `app/static/` is committed (see root `.gitignore`); `data/` is gitignored like `output/`.
- After every backend task: `uv run pytest -q` is green. After every frontend task: `npm run build` succeeds and the committed `app/static/` is updated.
- Run all `uv`/`pytest` commands from `resume-tailor-service/`; all `npm` commands from `resume-tailor-service/dashboard/`.

---

### Task 1: Remove backend auth

**Files:**
- Delete: `resume-tailor-service/app/auth.py`
- Delete: `resume-tailor-service/tests/test_auth.py`
- Modify: `resume-tailor-service/app/main.py`
- Modify: `resume-tailor-service/app/dashboard.py:20,32`
- Modify: `resume-tailor-service/tests/test_main.py`
- Modify: `resume-tailor-service/tests/test_dashboard.py`
- Modify: `resume-tailor-service/scripts/smoke_test.py:23-24`
- Modify: `resume-tailor-service/.env.example`

**Interfaces:**
- Produces: `app.main:app` and `dashboard.router` serve every route with no `Authorization` header required.

- [ ] **Step 1: Delete the auth-gate tests that will no longer hold**

Delete the whole file `tests/test_auth.py`. In `tests/test_main.py`, delete `test_tailor_rejects_missing_token` (asserts 401) and change `test_dashboard_router_is_mounted_and_requires_auth` to assert the router is mounted *without* auth:

```python
def test_dashboard_router_is_mounted():
    """GET /api/applications must resolve to the router (not 404). With no
    sheet configured it fails as a 502, which still proves it is mounted."""
    from fastapi.testclient import TestClient
    from app.main import app
    resp = TestClient(app).get("/api/applications")
    assert resp.status_code != 404
```

In `tests/test_main.py` also remove the `_token` fixture (the `monkeypatch.setenv("RESUME_TAILOR_TOKEN", ...)` one) and delete `headers={"Authorization": "Bearer test-token"}` from every `/tailor` POST call (the calls stay, just without the `headers=` kwarg). Keep `test_health_requires_no_auth` as-is.

In `tests/test_dashboard.py`: remove the `AUTH = {"Authorization": "Bearer test-token"}` line (18); remove `monkeypatch.setenv("RESUME_TAILOR_TOKEN", "test-token")` from the `client` fixture; remove `, headers=AUTH` from every `client.get(...)` call; delete `test_applications_requires_auth`, `test_get_tailored_requires_auth`, and `test_resume_bank_requires_auth`.

- [ ] **Step 2: Remove the auth wiring from the app**

Delete `app/auth.py`. In `app/dashboard.py`, change line 20 (`from app.auth import verify_token`) — remove it — and line 32:

```python
router = APIRouter()
```

Remove `Depends` from the `from fastapi import ...` line in `dashboard.py` (now unused). In `app/main.py`, remove `from app.auth import verify_token`, drop `Depends` from `from fastapi import FastAPI, Depends, HTTPException` (→ `from fastapi import FastAPI, HTTPException`), and change the handler signature:

```python
@app.post("/tailor", response_model=TailorResponse)
def tailor_resume(req: TailorRequest):
```

- [ ] **Step 3: De-token the smoke test and env example**

In `scripts/smoke_test.py` remove lines 23-24 (the `token = os.environ["RESUME_TAILOR_TOKEN"]` and `headers = {...}`) and the `headers=headers` kwarg on the POST (call `httpx.post(f"{base_url}/tailor", json={...}, timeout=60)`). Remove the now-unused `import os` only if nothing else uses it (it still reads `RESUME_TAILOR_URL` via `os.environ.get`, so keep `import os`).

In `.env.example`, delete the `RESUME_TAILOR_TOKEN=...` line and its preceding comment line, leaving the `APPS_SCRIPT_URL` / `APPS_SCRIPT_READ_SECRET` block. Result:

```
# Requires the Claude Code CLI (`claude`) installed and logged in (run `claude` once). No Anthropic API key needed.

# Dashboard read source: Google Apps Script /exec URL + its READ_SECRET.
# Read only by app/sheets.py; never returned to clients. For local runs these
# point at scripts/mock_sheet.py (see scripts/start.sh).
APPS_SCRIPT_URL=
APPS_SCRIPT_READ_SECRET=
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all remaining tests green; the deleted auth tests are gone; no `ModuleNotFoundError: app.auth`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "resume-tailor-service: remove bearer auth (local-only service)"
```

---

### Task 2: Promote mock sheet server + single start script

**Files:**
- Create: `resume-tailor-service/scripts/mock_sheet.py`
- Create: `resume-tailor-service/scripts/start.sh`
- Modify: `resume-tailor-service/README.md`

**Interfaces:**
- Produces: `./scripts/start.sh` boots `mock_sheet.py` (when `APPS_SCRIPT_URL` is local) + `uvicorn app.main:app --host 127.0.0.1 --port 8420`, and kills the mock on exit.

- [ ] **Step 1: Add the mock sheet server**

Create `scripts/mock_sheet.py` (a stand-in Apps Script `?action=read` endpoint; the first three rows join to existing `output/` tailored resumes):

```python
"""Local stand-in for the Google Apps Script /exec read endpoint.

GET /exec?action=read[&secret=...] -> {"ok": true, "rows": [...]}, mirroring the
contract app/sheets.py expects. Started by scripts/start.sh for local runs.
Run directly: APPS_SCRIPT_READ_SECRET=<s> python3 scripts/mock_sheet.py 8799
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROWS = [
    {"company": "Acme Cloud", "role": "Backend Engineer", "source": "LinkedIn",
     "jobUrl": "https://example.com/acme", "status": "applied", "fit": "8",
     "people": "", "hooks": "distributed systems, message queues", "outreach": "",
     "notes": "strong match on Go/Python + CI/CD", "timestamp": "2026-07-23T06:05:00Z"},
    {"company": "Vectra AI", "role": "AI/ML Engineer", "source": "Wellfound",
     "jobUrl": "https://example.com/vectra", "status": "people-mined", "fit": "9",
     "people": "CTO, Eng Lead", "hooks": "RAG, vector DB, LLM failover", "outreach": "",
     "notes": "Document Intelligence Platform is a direct match",
     "timestamp": "2026-07-23T06:10:00Z"},
    {"company": "Ridewell", "role": "Mobile Engineer", "source": "Referral",
     "jobUrl": "https://example.com/ridewell", "status": "outreach-sent", "fit": "7",
     "people": "Hiring Manager", "hooks": "React Native, native modules",
     "outreach": "connection note sent", "notes": "2 prod RN apps at Jythu",
     "timestamp": "2026-07-23T06:11:00Z"},
    {"company": "Northwind Labs", "role": "Full-Stack Engineer", "source": "Company site",
     "jobUrl": "https://example.com/northwind", "status": "interview", "fit": "8",
     "people": "", "hooks": "Next.js, Postgres", "outreach": "",
     "notes": "awaiting scheduling", "timestamp": "2026-07-22T18:00:00Z"},
    {"company": "Globex", "role": "Platform Engineer", "source": "LinkedIn",
     "jobUrl": "https://example.com/globex", "status": "rejected", "fit": "6",
     "people": "", "hooks": "K8s, Terraform", "outreach": "",
     "notes": "went with a senior candidate", "timestamp": "2026-07-21T12:00:00Z"},
]
SECRET = os.environ.get("APPS_SCRIPT_READ_SECRET", "").strip()


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if (qs.get("action") or [""])[0] != "read":
            return self._json({"ok": False, "error": "unknown action"})
        if SECRET and (qs.get("secret") or [""])[0] != SECRET:
            return self._json({"ok": False, "error": "bad secret"})
        return self._json({"ok": True, "rows": ROWS})

    def log_message(self, fmt, *args):
        sys.stderr.write("[mock_sheet] " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"[mock_sheet] serving {len(ROWS)} rows on http://127.0.0.1:{port}/exec")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
```

- [ ] **Step 2: Add the single start script**

Create `scripts/start.sh` (executable):

```bash
#!/usr/bin/env bash
# One command to run everything locally: mock sheet (if APPS_SCRIPT_URL is local)
# + the FastAPI service bound to loopback. Ctrl-C tears both down.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env so we can see APPS_SCRIPT_URL / secret.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

uv sync

MOCK_PID=""
cleanup() { [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Start the mock only when the configured sheet URL is local.
if printf '%s' "${APPS_SCRIPT_URL:-}" | grep -qE '127\.0\.0\.1|localhost'; then
  PORT="$(printf '%s' "$APPS_SCRIPT_URL" | sed -E 's#.*:([0-9]+).*#\1#')"
  echo "Starting mock sheet on port ${PORT}…"
  APPS_SCRIPT_READ_SECRET="${APPS_SCRIPT_READ_SECRET:-}" \
    python3 scripts/mock_sheet.py "$PORT" &
  MOCK_PID=$!
fi

echo "Starting API on http://127.0.0.1:8420 …"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8420
```

Then make it executable: `chmod +x scripts/start.sh`.

- [ ] **Step 3: Verify the script boots the stack**

Run (from `resume-tailor-service/`): `./scripts/start.sh` in one terminal, then in another:
```bash
curl -s http://localhost:8420/health          # -> {"status":"ok"}
curl -s http://127.0.0.1:8420/api/applications # -> JSON rows (no auth header needed)
```
Expected: health ok; applications returns 5 rows. Ctrl-C the script and confirm the mock process is gone (`pgrep -f mock_sheet.py` returns nothing).

- [ ] **Step 4: Document it in the README**

In `README.md`, replace the "Run locally" section and the token setup with: `cp .env.example .env` (fill only `APPS_SCRIPT_URL`/`APPS_SCRIPT_READ_SECRET`, or point `APPS_SCRIPT_URL` at `http://127.0.0.1:8799/exec` for the mock), then **`./scripts/start.sh`**. Remove the `Authorization: Bearer` header from the `curl /tailor` example. Add a one-line note: *"Local-only — the service has no auth and binds to 127.0.0.1. Re-add a token dependency before exposing it on a network."*

- [ ] **Step 5: Commit**

```bash
git add scripts/mock_sheet.py scripts/start.sh README.md
git commit -m "resume-tailor-service: add scripts/start.sh + repo mock sheet server"
```

---

### Task 3: Person data model

**Files:**
- Modify: `resume-tailor-service/app/models.py`
- Test: `resume-tailor-service/tests/test_models.py`

**Interfaces:**
- Produces: `app.models.Link{label:str,url:str}`, `app.models.PersonInput{name,title,company,role,linkedin_url,links,status,hook,message,notes}`, `app.models.Person(PersonInput + id,created_at,updated_at)`, and `app.models.PERSON_STATUSES: tuple[str,...]`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError
from app.models import Person, PersonInput, Link, PERSON_STATUSES


def test_person_input_defaults():
    p = PersonInput(name="Jane Doe", company="Vectra AI")
    assert p.status == "to-reach"
    assert p.role is None
    assert p.links == []
    assert p.title == "" and p.linkedin_url == "" and p.message == ""


def test_person_input_rejects_blank_name():
    with pytest.raises(ValidationError):
        PersonInput(name="   ", company="Vectra AI")


def test_person_input_rejects_blank_company():
    with pytest.raises(ValidationError):
        PersonInput(name="Jane", company="")


def test_person_input_rejects_unknown_status():
    with pytest.raises(ValidationError):
        PersonInput(name="Jane", company="Vectra AI", status="following-up")


def test_person_input_accepts_links_and_known_status():
    p = PersonInput(name="Jane", company="Vectra AI", status="sent",
                    links=[Link(label="GitHub", url="https://github.com/jane")])
    assert p.status == "sent"
    assert p.links[0].label == "GitHub"


def test_person_extends_input_with_server_fields():
    p = Person(name="Jane", company="Vectra AI", id="abc123",
               created_at="2026-07-23T00:00:00+00:00",
               updated_at="2026-07-23T00:00:00+00:00")
    assert p.id == "abc123" and p.name == "Jane"


def test_person_statuses_constant():
    assert PERSON_STATUSES == ("to-reach", "queued", "sent", "replied", "skip")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL (`ImportError: cannot import name 'Person'`).

- [ ] **Step 3: Implement the models**

Append to `app/models.py` (top of file already has `from pydantic import BaseModel`; add `field_validator`):

```python
from pydantic import field_validator

PERSON_STATUSES = ("to-reach", "queued", "sent", "replied", "skip")


class Link(BaseModel):
    label: str = ""
    url: str = ""


class PersonInput(BaseModel):
    name: str
    title: str = ""
    company: str
    role: str | None = None
    linkedin_url: str = ""
    links: list[Link] = []
    status: str = "to-reach"
    hook: str = ""
    message: str = ""
    notes: str = ""

    @field_validator("name", "company")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in PERSON_STATUSES:
            raise ValueError(f"status must be one of {PERSON_STATUSES}")
        return v


class Person(PersonInput):
    id: str
    created_at: str
    updated_at: str
```

Change the existing top import line to `from pydantic import BaseModel, field_validator` (do not add a second `from pydantic import` line).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "resume-tailor-service: add Person/PersonInput/Link models"
```

---

### Task 4: People JSON store

**Files:**
- Create: `resume-tailor-service/app/people_store.py`
- Test: `resume-tailor-service/tests/test_people_store.py`
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Consumes: `app.models.Person`, `app.models.PersonInput`.
- Produces: `people_store.STORE_PATH: Path` (module-level, monkeypatchable); `load_people() -> list[Person]`; `get_person(id) -> Person | None`; `add_person(PersonInput) -> Person`; `update_person(id, PersonInput) -> Person | None`; `delete_person(id) -> bool`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_people_store.py`:

```python
from pathlib import Path
import app.people_store as store
from app.models import PersonInput


def _use_temp(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "people.json")


def test_missing_file_is_empty(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    assert store.load_people() == []


def test_add_assigns_id_and_timestamps(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert p.id and p.created_at and p.updated_at
    assert store.STORE_PATH.is_file()
    people = store.load_people()
    assert len(people) == 1 and people[0].name == "Jane"


def test_update_changes_fields_keeps_created_at(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    updated = store.update_person(p.id, PersonInput(name="Jane Doe", company="Vectra AI", status="sent"))
    assert updated is not None
    assert updated.name == "Jane Doe" and updated.status == "sent"
    assert updated.created_at == p.created_at


def test_update_unknown_returns_none(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    assert store.update_person("nope", PersonInput(name="X", company="Y")) is None


def test_delete_removes_and_reports(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert store.delete_person(p.id) is True
    assert store.load_people() == []
    assert store.delete_person(p.id) is False


def test_get_person(monkeypatch, tmp_path):
    _use_temp(monkeypatch, tmp_path)
    p = store.add_person(PersonInput(name="Jane", company="Vectra AI"))
    assert store.get_person(p.id).name == "Jane"
    assert store.get_person("missing") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_people_store.py -q`
Expected: FAIL (`ModuleNotFoundError: app.people_store`).

- [ ] **Step 3: Implement the store**

Create `app/people_store.py`:

```python
"""JSON-file store for outreach people. Local, single-user, no DB — mirrors the
project's 'filesystem is the index' approach. Writes are atomic (temp + replace)
and guarded by a lock (sync endpoints run in a threadpool)."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import Person, PersonInput

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "people.json"
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> list[dict]:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_name(STORE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_PATH)


def load_people() -> list[Person]:
    out = []
    for raw in _read():
        try:
            out.append(Person.model_validate(raw))
        except ValueError:
            continue  # skip corrupt rows, never crash the list
    return out


def get_person(person_id: str) -> Person | None:
    for raw in _read():
        if raw.get("id") == person_id:
            return Person.model_validate(raw)
    return None


def add_person(data: PersonInput) -> Person:
    with _LOCK:
        items = _read()
        now = _now()
        person = Person(**data.model_dump(), id=uuid.uuid4().hex,
                        created_at=now, updated_at=now)
        items.append(person.model_dump())
        _write(items)
        return person


def update_person(person_id: str, data: PersonInput) -> Person | None:
    with _LOCK:
        items = _read()
        for i, raw in enumerate(items):
            if raw.get("id") == person_id:
                person = Person(**data.model_dump(), id=person_id,
                                created_at=raw.get("created_at", _now()),
                                updated_at=_now())
                items[i] = person.model_dump()
                _write(items)
                return person
        return None


def delete_person(person_id: str) -> bool:
    with _LOCK:
        items = _read()
        kept = [raw for raw in items if raw.get("id") != person_id]
        if len(kept) == len(items):
            return False
        _write(kept)
        return True
```

- [ ] **Step 4: Gitignore the store dir**

In the repo-root `.gitignore`, directly after the `resume-tailor-service/output/` line, add:

```
# Local people/outreach store (personal runtime data)
resume-tailor-service/data/
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_people_store.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/people_store.py tests/test_people_store.py ../.gitignore
git commit -m "resume-tailor-service: add people_store (atomic JSON CRUD)"
```

---

### Task 5: People API router + mount

**Files:**
- Create: `resume-tailor-service/app/people.py`
- Modify: `resume-tailor-service/app/main.py` (imports + `include_router`)
- Test: `resume-tailor-service/tests/test_people_api.py`

**Interfaces:**
- Consumes: `app.people_store`, `app.models.Person/PersonInput`.
- Produces: `people.router` with `GET /api/people` (opt `?company=`), `POST /api/people` (201), `PUT /api/people/{id}`, `DELETE /api/people/{id}` (204).

- [ ] **Step 1: Write failing tests**

Create `tests/test_people_api.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.people_store as store
from app import people


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "people.json")
    api = FastAPI()
    api.include_router(people.router)
    return TestClient(api)


def _mk(client, **over):
    body = {"name": "Jane Doe", "company": "Vectra AI"}
    body.update(over)
    return client.post("/api/people", json=body)


def test_create_returns_201_with_id(client):
    resp = _mk(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] and body["status"] == "to-reach"


def test_list_and_company_filter(client):
    _mk(client, company="Vectra AI")
    _mk(client, name="Bob", company="Acme Cloud")
    assert len(client.get("/api/people").json()) == 2
    only = client.get("/api/people", params={"company": "vectra ai"}).json()
    assert len(only) == 1 and only[0]["company"] == "Vectra AI"


def test_create_422_on_blank_name(client):
    assert _mk(client, name="").status_code == 422


def test_create_422_on_bad_status(client):
    assert _mk(client, status="following-up").status_code == 422


def test_update(client):
    pid = _mk(client).json()["id"]
    resp = client.put(f"/api/people/{pid}", json={"name": "Jane D", "company": "Vectra AI", "status": "sent"})
    assert resp.status_code == 200 and resp.json()["status"] == "sent"


def test_update_unknown_404(client):
    resp = client.put("/api/people/deadbeef", json={"name": "X", "company": "Y"})
    assert resp.status_code == 404


def test_update_bad_id_400(client):
    resp = client.put("/api/people/..%2fetc", json={"name": "X", "company": "Y"})
    assert resp.status_code in (400, 404)  # rejected, never applied


def test_delete(client):
    pid = _mk(client).json()["id"]
    assert client.delete(f"/api/people/{pid}").status_code == 204
    assert client.delete(f"/api/people/{pid}").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_people_api.py -q`
Expected: FAIL (`ImportError`/`AttributeError: module 'app.people' has no attribute 'router'`).

- [ ] **Step 3: Implement the router**

Create `app/people.py`:

```python
"""Read/write API for outreach people. No auth (local-only service)."""
import re

from fastapi import APIRouter, HTTPException

from app import people_store
from app.models import Person, PersonInput

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

router = APIRouter()


def _validate_id(person_id: str) -> None:
    if ".." in person_id or not _ID_RE.match(person_id):
        raise HTTPException(status_code=400, detail="invalid person id")


@router.get("/api/people", response_model=list[Person])
def list_people(company: str | None = None) -> list[Person]:
    people = people_store.load_people()
    if company:
        key = company.strip().lower()
        people = [p for p in people if p.company.strip().lower() == key]
    return people


@router.post("/api/people", response_model=Person, status_code=201)
def create_person(data: PersonInput) -> Person:
    return people_store.add_person(data)


@router.put("/api/people/{person_id}", response_model=Person)
def replace_person(person_id: str, data: PersonInput) -> Person:
    _validate_id(person_id)
    updated = people_store.update_person(person_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="person not found")
    return updated


@router.delete("/api/people/{person_id}", status_code=204)
def remove_person(person_id: str) -> None:
    _validate_id(person_id)
    if not people_store.delete_person(person_id):
        raise HTTPException(status_code=404, detail="person not found")
```

- [ ] **Step 4: Mount it in the app**

In `app/main.py`, add `people` to the existing app import line (`from app import tailor, render, dashboard, people`) and add the router include right after the dashboard include (before the StaticFiles mount):

```python
app.include_router(dashboard.router)
app.include_router(people.router)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_people_api.py -q && uv run pytest -q`
Expected: both PASS (new file green; whole suite still green).

- [ ] **Step 6: Commit**

```bash
git add app/people.py app/main.py tests/test_people_api.py
git commit -m "resume-tailor-service: add /api/people CRUD router"
```

---

### Task 6: Frontend — remove the token gate

**Files:**
- Delete: `resume-tailor-service/dashboard/src/components/TokenScreen.tsx`
- Modify: `resume-tailor-service/dashboard/src/api.ts`
- Modify: `resume-tailor-service/dashboard/src/App.tsx`
- Modify: `resume-tailor-service/dashboard/src/components/Inspector.tsx`

**Interfaces:**
- Produces: `api.ts` exports `apiFetch`, `fetchApplications`, `fetchTailored`, `loadResumeBank`, `resetBankCache`, `ApiError` (no token/`getToken`/`UNAUTHORIZED_EVENT`). The app renders the board with no auth step.

- [ ] **Step 1: Strip the token from `api.ts`**

Replace the token/`authedFetch` machinery (lines 1-49) so requests are plain fetch, and drop `fetchTailoredPdf` (the inspector will use a direct `src` now). New top of `api.ts`:

```typescript
// Same-origin API client. The service is local-only and unauthenticated, so
// requests are plain fetch with no Authorization header.

import type { Application, ResumeBank, TailoredResumeMeta } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, init);
}
```

Then in `fetchApplications`, `fetchTailored`, and `loadResumeBank`, replace every `authedFetch(` with `apiFetch(`. Delete the `fetchTailoredPdf` function entirely. Keep `resetBankCache`.

- [ ] **Step 2: Simplify `App.tsx` (no token state)**

Remove the token gate from `App.tsx`: delete the `TokenScreen` import; delete the `import { UNAUTHORIZED_EVENT, clearToken, getToken, setToken as persistToken } from "./api"` token pieces (keep `fetchApplications`, `resetBankCache`); delete the `token`/`authError` state, the `UNAUTHORIZED_EVENT` `useEffect`, `handleToken`, and the `if (!token) return <TokenScreen .../>` block. Drive loading off mount instead of `token`:

```typescript
// replace the token-gated effect
useEffect(() => {
  void load();
}, [load]);
```

Remove the "Sign out" button from the header (and `handleSignOut`, `clearToken`, `LogOut` import). The component returns the dashboard shell directly.

- [ ] **Step 3: Direct-`src` PDF in `Inspector.tsx`**

In `Inspector.tsx`, remove the `fetchTailoredPdf` import and the whole `pdfUrl`/`pdfError` blob `useEffect` (lines ~169-188) plus their state. Render the PDF straight from the authless route:

```tsx
{id != null && (
  <iframe
    title="Tailored resume PDF"
    src={`/api/tailored/${encodeURIComponent(id)}/pdf`}
    className="h-full w-full flex-1 border-0 bg-white"
  />
)}
```

Keep the metadata/bank `useEffect` (it uses `fetchTailored`/`loadResumeBank`, still present).

- [ ] **Step 4: Build and verify no gate**

Run: `npm install` (once) then `npm run build`
Expected: build succeeds, `app/static/` updates. Then from `resume-tailor-service/` start `./scripts/start.sh`, open `http://localhost:8420/` in the browser — the board loads **immediately with no token screen**, and opening a row with a tailored resume shows the embedded PDF.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "dashboard: remove token gate (local-only, direct PDF src)"
```

---

### Task 7: Frontend — People types, api helpers, and the People view

**Files:**
- Modify: `resume-tailor-service/dashboard/src/types.ts`
- Modify: `resume-tailor-service/dashboard/src/api.ts`
- Create: `resume-tailor-service/dashboard/src/lib/people.ts`
- Create: `resume-tailor-service/dashboard/src/components/PersonForm.tsx`
- Create: `resume-tailor-service/dashboard/src/components/People.tsx`
- Modify: `resume-tailor-service/dashboard/src/App.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `ApiError` from `api.ts`.
- Produces: `types.ts` `Person`, `PersonInput`, `Link`; `api.ts` `listPeople()`, `createPerson(PersonInput)`, `updatePerson(id, PersonInput)`, `deletePerson(id)`; `lib/people.ts` `PERSON_STATUSES`, `companyKey(s)`, `matchesApplication(person, {company, role})`; `<People>` view; a third `"people"` value in `App.tsx`'s `View`.

- [ ] **Step 1: Add People types**

Append to `types.ts`:

```typescript
export interface Link {
  label: string;
  url: string;
}

export interface PersonInput {
  name: string;
  title: string;
  company: string;
  role: string | null;
  linkedin_url: string;
  links: Link[];
  status: string;
  hook: string;
  message: string;
  notes: string;
}

export interface Person extends PersonInput {
  id: string;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Add People api helpers**

Append to `api.ts`:

```typescript
import type { Person, PersonInput } from "./types";

export async function listPeople(): Promise<Person[]> {
  const res = await apiFetch("/api/people");
  if (!res.ok) throw new ApiError(`Failed to load people (HTTP ${res.status}).`, res.status);
  return (await res.json()) as Person[];
}

async function writePerson(path: string, method: string, body: PersonInput): Promise<Person> {
  const res = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`Failed to save person (HTTP ${res.status}).`, res.status);
  return (await res.json()) as Person;
}

export function createPerson(body: PersonInput): Promise<Person> {
  return writePerson("/api/people", "POST", body);
}

export function updatePerson(id: string, body: PersonInput): Promise<Person> {
  return writePerson(`/api/people/${encodeURIComponent(id)}`, "PUT", body);
}

export async function deletePerson(id: string): Promise<void> {
  const res = await apiFetch(`/api/people/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(`Failed to delete person (HTTP ${res.status}).`, res.status);
}
```

Merge the `import type { Person, PersonInput }` into the existing `import type { ... } from "./types"` line rather than adding a duplicate import.

- [ ] **Step 3: Add the people helper lib**

Create `lib/people.ts`:

```typescript
import type { Person } from "../types";

export const PERSON_STATUSES = ["to-reach", "queued", "sent", "replied", "skip"] as const;

export const STATUS_LABEL: Record<string, string> = {
  "to-reach": "To reach", queued: "Queued", sent: "Sent", replied: "Replied", skip: "Skip",
};

export const STATUS_STYLE: Record<string, string> = {
  "to-reach": "bg-amber-500/15 text-amber-300 border-amber-500/30",
  queued: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  sent: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  replied: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  skip: "bg-slate-600/20 text-slate-400 border-slate-600/40",
};

const ORDER = new Map(PERSON_STATUSES.map((s, i) => [s, i]));
export function statusRank(s: string): number {
  return ORDER.get(s) ?? PERSON_STATUSES.length;
}

export function companyKey(company: string): string {
  return company.trim().toLowerCase();
}

/** True when a person should show under an application row. Company-level match;
 * when the person pinned a role, require that too. */
export function matchesApplication(p: Person, app: { company: string; role: string }): boolean {
  if (companyKey(p.company) !== companyKey(app.company)) return false;
  if (p.role && p.role.trim()) return companyKey(p.role) === companyKey(app.role);
  return true;
}

/** Only http(s) links are safe to render as hrefs. */
export function safeHref(url: string): string | null {
  const u = url.trim();
  return /^https?:\/\//i.test(u) ? u : null;
}
```

- [ ] **Step 4: Add the PersonForm modal**

Create `components/PersonForm.tsx`:

```tsx
import { useState } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import type { Person, PersonInput, Link } from "../types";
import { PERSON_STATUSES, STATUS_LABEL } from "../lib/people";

interface Props {
  initial?: Person | null;
  companies: string[];
  defaultCompany?: string;
  defaultRole?: string;
  onCancel: () => void;
  onSave: (body: PersonInput) => Promise<void>;
}

const EMPTY: PersonInput = {
  name: "", title: "", company: "", role: null, linkedin_url: "",
  links: [], status: "to-reach", hook: "", message: "", notes: "",
};

export default function PersonForm({ initial, companies, defaultCompany, defaultRole, onCancel, onSave }: Props) {
  const [form, setForm] = useState<PersonInput>(() =>
    initial
      ? { ...initial }
      : { ...EMPTY, company: defaultCompany ?? "", role: defaultRole ?? null }
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const set = <K extends keyof PersonInput>(k: K, v: PersonInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const setLink = (i: number, patch: Partial<Link>) =>
    setForm((f) => ({ ...f, links: f.links.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const addLink = () => setForm((f) => ({ ...f, links: [...f.links, { label: "", url: "" }] }));
  const removeLink = (i: number) => setForm((f) => ({ ...f, links: f.links.filter((_, j) => j !== i) }));

  const submit = async () => {
    setErr("");
    if (!form.name.trim() || !form.company.trim()) {
      setErr("Name and company are required.");
      return;
    }
    setSaving(true);
    try {
      await onSave({ ...form, role: form.role?.trim() ? form.role : null });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save.");
      setSaving(false);
    }
  };

  const field = "w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" onClick={onCancel}>
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">{initial ? "Edit person" : "Add person"}</h2>
          <button type="button" onClick={onCancel} className="rounded-md p-1 text-slate-400 hover:bg-slate-800" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-3 overflow-y-auto p-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Name*
              <input className={field} value={form.name} onChange={(e) => set("name", e.target.value)} />
            </label>
            <label className="text-xs text-slate-400">Title
              <input className={field} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Engineering Manager" />
            </label>
            <label className="text-xs text-slate-400">Company*
              <input className={field} list="known-companies" value={form.company} onChange={(e) => set("company", e.target.value)} />
              <datalist id="known-companies">{companies.map((c) => <option key={c} value={c} />)}</datalist>
            </label>
            <label className="text-xs text-slate-400">Role (optional tie)
              <input className={field} value={form.role ?? ""} onChange={(e) => set("role", e.target.value)} placeholder="Backend Engineer" />
            </label>
          </div>
          <label className="block text-xs text-slate-400">LinkedIn URL
            <input className={field} value={form.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} placeholder="https://linkedin.com/in/…" />
          </label>
          <div>
            <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
              <span>Extra links</span>
              <button type="button" onClick={addLink} className="inline-flex items-center gap-1 text-indigo-300 hover:text-indigo-200">
                <Plus className="h-3.5 w-3.5" /> Add link
              </button>
            </div>
            <div className="space-y-2">
              {form.links.map((l, i) => (
                <div key={i} className="flex gap-2">
                  <input className={field + " w-1/3"} value={l.label} onChange={(e) => setLink(i, { label: e.target.value })} placeholder="GitHub" />
                  <input className={field} value={l.url} onChange={(e) => setLink(i, { url: e.target.value })} placeholder="https://…" />
                  <button type="button" onClick={() => removeLink(i)} className="rounded-md p-1.5 text-slate-500 hover:text-rose-300" aria-label="Remove link">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Status
              <select className={field} value={form.status} onChange={(e) => set("status", e.target.value)}>
                {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-400">Hook
              <input className={field} value={form.hook} onChange={(e) => set("hook", e.target.value)} placeholder="angle for outreach" />
            </label>
          </div>
          <label className="block text-xs text-slate-400">Message
            <textarea className={field + " min-h-[64px]"} value={form.message} onChange={(e) => set("message", e.target.value)} placeholder="drafted / sent outreach text" />
          </label>
          <label className="block text-xs text-slate-400">Notes
            <textarea className={field + " min-h-[48px]"} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </label>
          {err && <p className="text-sm text-rose-400">{err}</p>}
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-800 px-4 py-3">
          <button type="button" onClick={onCancel} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={submit} disabled={saving}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Add the People view**

Create `components/People.tsx`:

```tsx
import { useMemo, useState } from "react";
import { Plus, Pencil, Trash2, ExternalLink, Linkedin, Search } from "lucide-react";
import type { Person, PersonInput } from "../types";
import { createPerson, updatePerson, deletePerson } from "../api";
import { PERSON_STATUSES, STATUS_LABEL, STATUS_STYLE, statusRank, safeHref } from "../lib/people";
import PersonForm from "./PersonForm";

interface Props {
  people: Person[];
  companies: string[];
  onChanged: () => void;
}

export default function People({ people, companies, onChanged }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [editing, setEditing] = useState<Person | null>(null);
  const [adding, setAdding] = useState(false);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => status === "all" || p.status === status)
      .filter((p) =>
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.company.toLowerCase().includes(q) ||
        p.title.toLowerCase().includes(q)
      )
      .sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.company.localeCompare(b.company));
  }, [people, query, status]);

  const save = async (body: PersonInput) => {
    if (editing) await updatePerson(editing.id, body);
    else await createPerson(body);
    setEditing(null);
    setAdding(false);
    onChanged();
  };

  const remove = async (p: Person) => {
    await deletePerson(p.id);
    onChanged();
  };

  const chip = "inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search people…"
            className="w-56 rounded-lg border border-slate-800 bg-slate-900 py-1.5 pl-7 pr-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-sm text-slate-300">
          <option value="all">All statuses</option>
          {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <span className="text-xs text-slate-500">{shown.length} of {people.length}</span>
        <button type="button" onClick={() => setAdding(true)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500">
          <Plus className="h-3.5 w-3.5" /> Add person
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-10 text-center text-sm text-slate-500">
          No people yet. Click “Add person” to start your outreach list.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Name</th><th className="px-3 py-2">Company</th>
                <th className="px-3 py-2">Status</th><th className="px-3 py-2">Links</th>
                <th className="px-3 py-2">Hook</th><th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {shown.map((p) => (
                <tr key={p.id} className="hover:bg-slate-900/40">
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-100">{p.name}</div>
                    <div className="text-xs text-slate-500">{p.title}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-300">
                    {p.company}{p.role ? <span className="text-slate-500"> · {p.role}</span> : null}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-xs ${STATUS_STYLE[p.status] ?? ""}`}>
                      {STATUS_LABEL[p.status] ?? p.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {safeHref(p.linkedin_url) && (
                        <a className={chip} href={safeHref(p.linkedin_url)!} target="_blank" rel="noopener noreferrer">
                          <Linkedin className="h-3 w-3" /> LinkedIn
                        </a>
                      )}
                      {p.links.map((l, i) => safeHref(l.url) && (
                        <a key={i} className={chip} href={safeHref(l.url)!} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-3 w-3" /> {l.label || "link"}
                        </a>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2 max-w-[16rem] truncate text-slate-400" title={p.hook}>{p.hook}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button type="button" onClick={() => setEditing(p)} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100" aria-label="Edit"><Pencil className="h-4 w-4" /></button>
                      <button type="button" onClick={() => remove(p)} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(adding || editing) && (
        <PersonForm
          initial={editing}
          companies={companies}
          onCancel={() => { setAdding(false); setEditing(null); }}
          onSave={save}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 6: Wire the third view into `App.tsx`**

In `App.tsx`: extend the view type to `type View = "board" | "table" | "people";`. Add state + loader for people near the apps state:

```typescript
import { listPeople } from "./api";
import type { Person } from "./types";
import People from "./components/People";
import { Users } from "lucide-react";
// ...
const [people, setPeople] = useState<Person[]>([]);
const loadPeople = useCallback(async () => {
  try { setPeople(await listPeople()); } catch { /* non-fatal for the board */ }
}, []);
useEffect(() => { void loadPeople(); }, [loadPeople]);

const companies = useMemo(
  () => Array.from(new Set(apps.map((a) => a.company).filter(Boolean))).sort(),
  [apps]
);
```

Add a **People** button to the header toggle group (next to Board):

```tsx
<button type="button" onClick={() => setView("people")} aria-pressed={view === "people"}
  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
    view === "people" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"}`}>
  <Users className="h-3.5 w-3.5" aria-hidden /> People
</button>
```

In the `phase === "ready"` block, render People when selected, else the existing stats/filter/table:

```tsx
{view === "people" ? (
  <People people={people} companies={companies} onChanged={loadPeople} />
) : (
  <>
    <StatsHeader ... />
    <FilterBar ... />
    {view === "table" ? <AppTable ... /> : <Board ... />}
  </>
)}
```

(Leave the existing `StatsHeader`/`FilterBar`/`AppTable`/`Board` props exactly as they are.)

- [ ] **Step 7: Build and verify the People view**

Run: `npm run build`
Expected: build succeeds. Start `./scripts/start.sh`, open the dashboard, click **People** → add a person (name "Jane Doe", company "Vectra AI", a LinkedIn URL, status "sent") → it appears in the table with a clickable LinkedIn chip; edit and delete both work.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "dashboard: add People/Outreach hub view (CRUD + links + status)"
```

---

### Task 8: Frontend — People in the inspector + card count

**Files:**
- Modify: `resume-tailor-service/dashboard/src/components/Inspector.tsx`
- Modify: `resume-tailor-service/dashboard/src/App.tsx` (pass `people` to Inspector + a chip on cards)
- Modify: `resume-tailor-service/dashboard/src/components/AppTable.tsx` (people count column) — optional if a natural column exists; otherwise skip and keep the Board chip.

**Interfaces:**
- Consumes: `Person`, `matchesApplication`, `safeHref` from `lib/people.ts`; `people` list from `App.tsx`.
- Produces: Inspector renders a "People at {company}" section; `App.tsx` passes `people` + an "add person for this listing" affordance.

- [ ] **Step 1: Replace the Mined Contacts panel**

In `Inspector.tsx`, change the props to accept the people list and an add callback:

```tsx
interface Props {
  app: Application;
  people: Person[];
  onClose: () => void;
  onAddPerson: (company: string, role: string) => void;
}
```

Replace `ContactsPanel` with a section that lists matched structured people (clickable links + status), keeps the sheet `hooks`, and keeps the raw sheet `people` string as a muted fallback:

```tsx
import { matchesApplication, safeHref, STATUS_LABEL, STATUS_STYLE } from "../lib/people";
import type { Person } from "../types";
import { Linkedin, ExternalLink, UserPlus } from "lucide-react";

function PeoplePanel({ app, people, onAddPerson }: { app: Application; people: Person[]; onAddPerson: (c: string, r: string) => void }) {
  const matched = people.filter((p) => matchesApplication(p, { company: app.company, role: app.role }));
  const hooks = app.hooks.trim();
  const rawPeople = app.people.trim();
  const chip = "inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300";
  return (
    <section className="border-t border-slate-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Users className="h-4 w-4 text-slate-400" aria-hidden /> People at {app.company || "this company"}
        </h3>
        <button type="button" onClick={() => onAddPerson(app.company, app.role)}
          className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300">
          <UserPlus className="h-3.5 w-3.5" /> Add
        </button>
      </div>
      {matched.length > 0 ? (
        <ul className="space-y-2">
          {matched.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-slate-100">{p.name}</span>
              {p.title && <span className="text-slate-500">· {p.title}</span>}
              <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-xs ${STATUS_STYLE[p.status] ?? ""}`}>{STATUS_LABEL[p.status] ?? p.status}</span>
              {safeHref(p.linkedin_url) && <a className={chip} href={safeHref(p.linkedin_url)!} target="_blank" rel="noopener noreferrer"><Linkedin className="h-3 w-3" /> LinkedIn</a>}
              {p.links.map((l, i) => safeHref(l.url) && <a key={i} className={chip} href={safeHref(l.url)!} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-3 w-3" /> {l.label || "link"}</a>)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-600">No people added for this company yet.</p>
      )}
      {(hooks || rawPeople) && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 text-xs text-slate-500">
          {hooks && <div><div className="mb-1 uppercase tracking-wide">Hooks (sheet)</div><p className="whitespace-pre-wrap text-slate-400">{hooks}</p></div>}
          {rawPeople && <div><div className="mb-1 uppercase tracking-wide">Raw sheet note</div><p className="whitespace-pre-wrap text-slate-400">{rawPeople}</p></div>}
        </div>
      )}
    </section>
  );
}
```

Replace both `<ContactsPanel app={app} />` usages with `<PeoplePanel app={app} people={people} onAddPerson={onAddPerson} />` and delete the old `ContactsPanel`.

- [ ] **Step 2: Pass people + wiring from `App.tsx`**

Where `Inspector` is rendered, pass the list and an add handler that opens the People form prefilled. Simplest: hold a "prefill" request in `App.tsx` state and switch to the People view with the form open. Implement a lightweight version — clicking **Add** in the inspector switches to the People view:

```tsx
{selected && (
  <Inspector
    app={selected}
    people={people}
    onClose={() => setSelected(null)}
    onAddPerson={(company, role) => {
      setSelected(null);
      setView("people");
      // People view exposes its own Add button; the company/role are visible
      // on the row the user just came from. (A prefilled deep-link is a later nicety.)
      void role; void company;
    }}
  />
)}
```

- [ ] **Step 3: Add a people-count chip on the Board card**

In `components/Board.tsx`, the `AppCard` (or the card element) receives `people`. Pass `people` from `App.tsx` (`<Board apps={filteredApps} people={people} onOpen={setSelected} />`) and, inside the card, compute the count and render a chip when > 0:

```tsx
// in the card, given `people: Person[]` and `app`:
const count = people.filter((p) => matchesApplication(p, { company: app.company, role: app.role })).length;
// ...render near the fit badge:
{count > 0 && (
  <span className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-400">
    <Users className="h-3 w-3" /> {count}
  </span>
)}
```

Add the matching prop types (`people: Person[]`) to `Board`/`AppCard` and the `Users` + `matchesApplication` imports. (If threading `people` into `Board` is awkward, this chip is optional polish — the inspector section is the required surface.)

- [ ] **Step 4: Build and verify**

Run: `npm run build`
Expected: build succeeds. Start `./scripts/start.sh`; open the **Vectra AI** row → the inspector shows "People at Vectra AI" listing the person you added, with a clickable LinkedIn link and status badge; the Board card for Vectra AI shows a "1" people chip.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "dashboard: surface people per-job in the inspector + card count"
```

---

### Task 9: Docs + full end-to-end verification

**Files:**
- Modify: `resume-tailor-service/README.md`

- [ ] **Step 1: Finalize the README**

Add a short **"People / Outreach hub"** section to `README.md`: the dashboard's third view is a central list of people to reach out to (LinkedIn + extra links, status, message, optional job tie); people are stored in `data/people.json` (gitignored, local-only); managed via `POST/PUT/DELETE /api/people`. Reiterate the local-only / no-auth note.

- [ ] **Step 2: Full backend suite**

Run: `uv run pytest -q`
Expected: PASS (all tests, including `test_models.py`, `test_people_store.py`, `test_people_api.py`; no auth tests remain).

- [ ] **Step 3: Full stack smoke via the start script**

Run `./scripts/start.sh`, then:
```bash
curl -s -X POST http://localhost:8420/api/people -H 'Content-Type: application/json' \
  -d '{"name":"Dana Lee","company":"Acme Cloud","linkedin_url":"https://linkedin.com/in/dana","status":"to-reach"}'
curl -s http://localhost:8420/api/people | python3 -c "import json,sys;print(len(json.load(sys.stdin)),'people')"
```
Expected: create returns a JSON person with an `id`; list shows the count. In the browser: People view lists Dana Lee; the Acme Cloud job inspector shows her under "People at Acme Cloud"; the board loads with no token screen.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "resume-tailor-service: document People hub + local-only run"
```

---

## Self-Review Notes

- **Spec coverage:** Workstream 1 → Task 1 + Task 6; Workstream 2 → Task 2; Workstream 3 backend → Tasks 3–5; Workstream 3 frontend → Tasks 7–8; safety (scheme-checked links, atomic writes, id guard) → `safeHref` (Task 7), `people_store._write` (Task 4), `_validate_id` (Task 5); testing → Tasks 3–5 + Task 9; join semantics → `matchesApplication` (Task 7).
- **Status vocabulary** is identical in backend (`PERSON_STATUSES`, Task 3) and frontend (`lib/people.ts`, Task 7): `to-reach, queued, sent, replied, skip`.
- **Type consistency:** `PersonInput`/`Person` field names match across `models.py`, `types.ts`, store, router, and form. api.ts helper names (`listPeople`/`createPerson`/`updatePerson`/`deletePerson`) are used verbatim in `People.tsx` and `App.tsx`.
- **No new runtime env vars.** `RESUME_TAILOR_TOKEN` fully retired.
