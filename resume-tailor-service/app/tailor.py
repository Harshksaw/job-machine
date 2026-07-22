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
