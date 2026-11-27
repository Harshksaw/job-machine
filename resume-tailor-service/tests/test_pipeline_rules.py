"""Shared text rules (spec 6.2) for anything sendable: cover letters and form answers."""
import pytest

from app.models import ApplicationAnswer, JobWorkspace
from app.pipeline import rules

EM = "—"


def _words(n, word="word"):
    return " ".join([word] * n)


def test_em_dash_is_flagged():
    assert rules.em_dash_errors(f"Plain text {EM} with a dash", "answer") != []
    assert rules.em_dash_errors("Plain text, no dash", "answer") == []


@pytest.mark.parametrize("text", ["I like full-stack work", "a human-in-the-loop flow"])
def test_hyphenated_compounds_are_flagged(text):
    errors = rules.hyphen_compound_errors(text, "answer")
    assert errors and "hyphenated" in errors[0]


@pytest.mark.parametrize("text", ["H-1B status", "GPT-4 evals", "see a/b-c", "mail me@x-y.com",
                                  "range 2-5 years", "plain words only"])
def test_identifiers_and_numbers_are_not_compounds(text):
    assert rules.hyphen_compound_errors(text, "answer") == []


def test_banned_cover_phrases_and_ai_tells_are_flagged():
    errors = rules.banned_phrase_errors("I am writing to apply and I am passionate about it", "cover letter")
    assert any("i am writing to apply" in e for e in errors)
    assert any("passionate" in e for e in errors)
    assert rules.banned_phrase_errors("I built the sync job and it cut errors.", "answer") == []


def test_word_limits():
    assert rules.word_limit_errors(_words(10), "answer", max_words=120) == []
    assert "121" in rules.word_limit_errors(_words(121), "answer", max_words=120)[0]
    assert "119" in rules.word_limit_errors(_words(119), "cover letter", min_words=120, max_words=360)[0]


@pytest.mark.parametrize("company,text,ok", [
    ("Acme Cloud, Inc.", "Acme ships fast", True),
    ("OneClick / IXL Learning", "IXL has a real problem", True),
    ("Cerebras Systems", "Hello there team", False),
])
def test_company_named(company, text, ok):
    assert (rules.company_named_errors(text, company) == []) is ok


def test_cover_letter_errors_combines_every_rule():
    letter = f"Hello team {EM} I am a full-stack dev. " + _words(10)
    errors = rules.cover_letter_errors(letter, "Acme")
    joined = " ".join(errors)
    for part in ("em dash", "hyphenated", "words", "name the company"):
        assert part in joined
    good = "Acme builds payments. " + _words(150, "plain")
    assert rules.cover_letter_errors(good, "Acme") == []


def test_answer_errors_use_the_answer_word_limit():
    assert rules.answer_errors("Short and plain.") == []
    assert rules.answer_errors(_words(130)) != []
    assert rules.answer_errors(f"Yes {EM} sure") != []


def test_packet_issues_checks_letter_and_drafted_answers_only():
    answers = [
        ApplicationAnswer(id="a", question="Why us?", answer="I like full-stack work.",
                          created_at="t", updated_at="t"),
        ApplicationAnswer(id="b", question="Salary?", needs_user_input=True,
                          clarification="ask", created_at="t", updated_at="t"),
    ]
    job = JobWorkspace(id="j", company="Acme", role="Engineer", created_at="t", updated_at="t",
                       cover_letter="Hello there. " + _words(150, "plain"),
                       application_answers=answers)
    issues = rules.packet_issues(job)
    fields = [issue["field"] for issue in issues]
    assert "cover_letter" in fields and "Why us?" in fields and "Salary?" not in fields
    assert all(set(issue) == {"field", "problem", "fix"} for issue in issues)


def test_packet_issues_is_empty_for_a_clean_packet():
    job = JobWorkspace(id="j", company="Acme", role="Engineer", created_at="t", updated_at="t",
                       cover_letter="Acme builds payments. " + _words(150, "plain"))
    assert rules.packet_issues(job) == []
