# Agent orchestrator M4: agent and service steps

Spec: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` sections 4, 5.1,
5.3, 6 and 13.1. Builds on M1 (`runner.py`) and M3 (`steps_code.py`, `ats.py`).

## Files

- `app/pipeline/prompts/<step>.md` plus `app/pipeline/prompts.py`:
  `render(step_name, ctx, extra) -> (text, version)`. Agent neutral templates with
  `{{name}}` placeholders; version is the first 12 hex of sha256 of the template source.
  Adapters (M2) call it and append the JSON output footer.
- `app/pipeline/rules.py`: shared text rules (em dashes, hyphenated compounds, banned
  phrases, word limits, company named), used by kit, answers and review.
- `app/pipeline/steps_agent.py`: Pydantic output schemas, finish functions and builders
  for `eligibility`, `fit_score`, `company_context`, `form_fields`, `people`, `review`.
- `app/pipeline/steps_service.py`: `kit` and `answers` service steps over
  `application_kit.generate_kit` / `generate_answer` with the section 6.3 repair loop.
- `app/pipeline/pipelines.py`: `PACKET_PIPELINE`.
- `app/models.py`: new dossier fields `form_fields` (default empty) and `review`
  (default None), so old documents still load.

## Order of work (one commit each, test first)

1. prompts and templates.
2. rules.
3. models fields, then the agent steps (eligibility and fit_score; company_context,
   form_fields and people; review).
4. service steps kit and answers; an optional `previous_errors` on generate_kit and
   generate_answer, off by default.
5. pipelines: claim -> resolve_apply_url -> fetch_jd -> liveness -> eligibility ->
   fit_score -> (company_context, kit, form_fields, people) -> answers -> review ->
   brief(mark_ready). Owner ruling: resolve_apply_url moves ahead of fetch_jd and
   liveness in the M3 chain too, so board listings get their JD from the employer ATS.
6. End to end test with FakeAdapters, then an independent review and fixes.

## Rulings where the spec is silent

- fit_score is the gate authority. When the dossier already has fit_analysis, the step
  also writes fit_analysis with the new score and matching recommendation, because
  `update_job` overwrites fit_score from fit_analysis.score. The kit step pins its
  analysis score to the fit_score output for the same reason and records `kit_score`.
- The review driven repair round of 6.4 needs a runner that reruns an earlier step; M4
  does not add one. A failing review lands under NEEDS HARSH and the packet is still
  ready, which is the spec's end state after a failed repair.
- Agent fallbacks for fetch_jd and resolve_apply_url stay `needs_agent` outputs (M2+).
- answers skips personal value fields (name, contact, links, resume); judgment
  questions are kept and marked `needs_user_input` by the existing detection with no
  model call; free text fields with an existing answer for the same question are kept.
