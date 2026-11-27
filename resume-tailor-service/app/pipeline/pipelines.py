"""The packet pipeline: one dossier from intake to an apply packet.

    claim -> resolve_apply_url -> fetch_jd -> liveness -> eligibility -> fit_score
      -> (company_context, kit, form_fields, people) -> answers -> review -> repair -> brief

resolve_apply_url runs before fetch_jd and liveness (owner ruling, M4), so a board
listing gets its JD and its liveness check from the employer ATS. A fit below 6 ends
the run "retained_for_review" before anything is written for the application (rule 2);
people runs only at fit 8 and up. A failing review gets one repair round on what it
flagged (spec 6.4); brief then marks the dossier ready, with any open review issues
under NEEDS HARSH.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md section 4.
"""
from __future__ import annotations

from pathlib import Path

from app.pipeline import ats, steps_agent, steps_code, steps_service
from app.pipeline.runner import Pipeline, StepSpec

_FAN_OUT = ("company_context", "kit", "form_fields", "people")


def packet_steps(
    http: ats.Http | None = None,
    check: steps_code.Check | None = None,
    *,
    complete_kit: steps_service.Complete | None = None,
    complete_answer: steps_service.Complete | None = None,
    bank_path: Path | None = None,
) -> tuple[StepSpec, ...]:
    after_fit = ("fit_score",)
    return (
        *steps_code.intake_steps(http, check),
        steps_agent.eligibility_step(deps=("liveness",)),
        steps_agent.fit_score_step(deps=("eligibility",)),
        steps_agent.company_context_step(deps=after_fit),
        steps_service.kit_step(complete_kit, bank_path=bank_path, deps=after_fit),
        steps_agent.form_fields_step(deps=after_fit),
        steps_agent.people_step(deps=after_fit),
        steps_service.answers_step(complete_answer, bank_path=bank_path, deps=_FAN_OUT),
        steps_agent.review_step(deps=("answers",)),
        steps_service.repair_step(complete_kit, complete_answer, bank_path=bank_path,
                                  deps=("fit_score", "review")),
        steps_code.brief_step(deps=("repair",), mark_ready=True),
    )


PACKET_PIPELINE = Pipeline("packet", packet_steps())
