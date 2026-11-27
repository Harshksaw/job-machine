# Agent orchestrator M3: code steps

Spec: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` section 4.
Builds on M1 (`app/pipeline/runner.py`: `StepSpec`, `StepContext`, `StepResult`, `Pipeline`).

## Files

- `resume-tailor-service/app/pipeline/ats.py`: URL detection (Ashby, Greenhouse, Lever,
  LinkedIn, other ATS hosts, job board hosts), HTML to text, public JD fetchers. Every
  network call goes through one injectable `Http` callable `(method, url) -> (status,
  final_url, body)`; the default is plain `urllib` with a timeout and an honest User-Agent.
- `resume-tailor-service/app/pipeline/steps_code.py`: one builder per code step, plus
  `code_steps()` and `PACKET_CODE_PIPELINE` (claim -> fetch_jd -> liveness ->
  resolve_apply_url -> brief).
- `resume-tailor-service/tests/test_pipeline_steps_code.py`: every step run through
  `runner.run` on temp JSON stores, with synthetic fixture payloads (no network).

## Steps (one commit each, test first)

1. `claim`: refuse a fresh foreign claim (under 2 hours) with a step failure; stop
   `cancelled` / "already applied" on an `applied` activity or a post submission status;
   otherwise add the activity "Claimed by pipeline <run_id>" (an activity, not a field
   write, so it sits outside the runner's owns check). Idempotent on resume.
2. `fetch_jd`: keep 800+ char text; else fetch through the ATS public APIs and the
   LinkedIn guest endpoint; write `jd_text` only when longer; `needs_agent` when still
   short.
3. `liveness`: `scripts/check_liveness.check` (injectable); `closed` stops
   `closed_posting` and appends one line to `notes`.
4. `resolve_apply_url`: keep existing; accept an ATS `job_url`; follow board redirects
   and accept only an ATS posting or a careers page off board hosts; else `needs_agent`.
5. `brief`: plain text template with SUMMARY, APPLY AT, GAPS, WHAT TO PUT IN, NEEDS
   HARSH, PEOPLE; status `ready` only from `discovered` or `researching`.
6. `code_steps()` and `PACKET_CODE_PIPELINE`, then an independent review and fixes.
