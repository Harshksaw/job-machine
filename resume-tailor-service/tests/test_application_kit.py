import json
from pathlib import Path

import pytest

from app.application_kit import (
    build_source_index,
    generate_answer,
    generate_kit,
    validate_kit,
)
from app.bank import load_bank
from app.errors import JobGenerationError
from app.models import (
    GeneratedApplicationKit,
    JobWorkspace,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def _job() -> JobWorkspace:
    return JobWorkspace(
        id="job1",
        company="Acme Cloud",
        role="Backend Engineer",
        jd_text=(
            "Acme Cloud needs a Backend Engineer with FastAPI, AWS, and RAG "
            "experience. Build reliable services and work with product teams."
        ),
        activities=[],
        revisions=[],
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
    )


def _valid_kit_payload() -> dict:
    cover = """Acme Cloud needs a backend engineer who can connect reliable services with useful product outcomes. That is the work I have been doing across production platforms, where careful delivery matters as much as the implementation itself.

At Ommuse, I built a Go HubSpot sync for a 12K+ user music platform, including async batching and deduplication across 8 API trigger points. I also shipped infrastructure across AWS, Docker, Pulumi, and GitHub Actions. That experience maps directly to dependable backend ownership.

My Document Intelligence Platform adds the applied AI side: a multi-tenant RAG system using FastAPI, LangChain, and Qdrant, deployed on AWS ECS Fargate with idempotent ingestion. It gives me practical context for building RAG features while keeping failure handling and operations visible.

I would bring Acme Cloud evidence from shipped systems, a direct approach to unknowns, and the range to move between backend code, infrastructure, and product details. I would value a conversation about the Backend Engineer role and the problems the team wants this hire to own."""
    return {
        "analysis": {
            "score": 8,
            "recommendation": "apply",
            "verdict": "Strong backend and RAG evidence maps to the role.",
            "role_thesis": "Backend engineer with shipped FastAPI, AWS, and RAG systems.",
            "keywords": ["FastAPI", "AWS", "RAG"],
            "evidence": [
                {
                    "requirement": "FastAPI",
                    "strength": "strong",
                    "proof": "Built a FastAPI multi-tenant RAG platform.",
                    "source_ids": ["project.docintel.bullet.1"],
                },
                {
                    "requirement": "AWS",
                    "strength": "strong",
                    "proof": "Deployed the platform to AWS ECS Fargate.",
                    "source_ids": ["project.docintel.bullet.3"],
                },
                {
                    "requirement": "RAG",
                    "strength": "strong",
                    "proof": "Architected a multi-tenant RAG platform using Qdrant.",
                    "source_ids": ["project.docintel.bullet.1"],
                },
            ],
            "gaps": [],
            "positioning": ["Lead with production backend ownership and applied RAG."],
        },
        "cover_letter": cover,
    }


def test_generate_kit_accepts_traceable_sources():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    payload = _valid_kit_payload()
    kit = generate_kit(
        _job(),
        bank,
        complete=lambda _: json.dumps(payload),
        max_retries=0,
    )
    assert kit.analysis.score == 8
    assert "Acme Cloud" in kit.cover_letter


def test_validate_kit_rejects_unknown_source_and_inconsistent_score():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    payload = _valid_kit_payload()
    payload["analysis"]["score"] = 4
    payload["analysis"]["evidence"][0]["source_ids"] = ["invented.source"]
    kit = GeneratedApplicationKit.model_validate(payload)
    errors = validate_kit(kit, _job(), build_source_index(bank))
    assert any("score 6+" in error for error in errors)
    assert any("unknown source" in error for error in errors)


def test_validate_kit_keeps_low_fit_for_review_with_editable_letter():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    payload = _valid_kit_payload()
    payload["analysis"]["score"] = 4
    payload["analysis"]["recommendation"] = "review"
    kit = GeneratedApplicationKit.model_validate(payload)

    errors = validate_kit(kit, _job(), build_source_index(bank))

    assert not any("recommend" in error for error in errors)
    assert not any("cover letter" in error for error in errors)


def test_validate_kit_rejects_automatic_skip_for_low_fit():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    payload = _valid_kit_payload()
    payload["analysis"]["score"] = 4
    payload["analysis"]["recommendation"] = "skip"
    payload["cover_letter"] = ""
    kit = GeneratedApplicationKit.model_validate(payload)

    errors = validate_kit(kit, _job(), build_source_index(bank))

    assert any("score below 6 must recommend review" in error for error in errors)


def test_generate_kit_rejects_short_job_description():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    job = _job().model_copy(update={"jd_text": "Too short"})
    with pytest.raises(JobGenerationError, match="complete job description"):
        generate_kit(job, bank, complete=lambda _: "{}")


def test_sensitive_answer_never_calls_model():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    def fail_if_called(_: str) -> str:
        raise AssertionError("model should not be called")

    answer = generate_answer(
        _job(),
        bank,
        "What are your salary expectations?",
        complete=fail_if_called,
    )
    assert answer.needs_user_input is True
    assert answer.answer == ""
    assert "Confirm" in answer.clarification


def test_real_profile_preferences_are_in_source_ledger():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    sources = build_source_index(bank)
    assert sources["profile.relocation"] == "Open to relocation."
    assert "early-career" in sources["profile.target_roles"]


def test_verified_relocation_preference_can_be_answered():
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")
    answer = generate_answer(
        _job(),
        bank,
        "Are you willing to relocate?",
        complete=lambda _: json.dumps(
            {
                "answer": "Yes. I am open to relocation.",
                "source_ids": ["profile.relocation"],
                "needs_user_input": False,
                "clarification": "",
            }
        ),
        max_retries=0,
    )
    assert answer.needs_user_input is False
    assert answer.source_ids == ["profile.relocation"]
