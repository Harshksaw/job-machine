import pytest

from app.house_style import apply_house_style, voice_errors


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("I build agents — fast ones.", "I build agents, fast ones."),
        ("I build agents—fast ones.", "I build agents, fast ones."),
        ("Shipped it -- twice.", "Shipped it, twice."),
        ("2–4 years", "2 to 4 years"),
        ("a full-stack role", "a full stack role"),
        ("a human-in-the-loop gate", "a human in the loop gate"),
        ("Full-Stack Engineer", "Full Stack Engineer"),
        ("a multi-tenant platform", "a multitenant platform"),
        ("my co-founder", "my cofounder"),
        ("non-trivial work", "nontrivial work"),
    ],
)
def test_house_style_removes_dashes_and_hyphenated_compounds(raw, expected):
    assert apply_house_style(raw) == expected


@pytest.mark.parametrize(
    "kept",
    [
        "linkedin.com/in/harsh-kumar-s-32727b247",
        "https://jobs.ashbyhq.com/socure/d4231c05-fb34-488c",
        "mister.harsh-kumar@gmail.com",
        "an H-1B or TN visa",
        "GPT-4 and COVID-19",
        "claude-haiku-4-5",
    ],
)
def test_house_style_leaves_identifiers_alone(kept):
    """URLs, emails and digit-bearing identifiers are not prose compounds."""
    assert apply_house_style(kept) == kept


def test_house_style_keeps_paragraph_breaks():
    text = "First full-stack line.\n\nSecond line — done."
    assert apply_house_style(text) == "First full stack line.\n\nSecond line, done."


# Harsh, 2026-11-09: answers must read like him, not like a model: less stack, more impact.
@pytest.mark.parametrize("text", [
    "I am excited to apply because I am passionate about developer tools.",
    "I leveraged my skills to build a robust, seamless platform.",
    "This role aligns perfectly with my experience.",
    "In today's fast paced world, AI matters.",
    "I spearheaded the migration and it was a testament to teamwork.",
    "I would love the opportunity to contribute.",
])
def test_voice_flags_ai_tells(text):
    assert voice_errors(text, "answer")


def test_voice_flags_a_stacked_tech_list():
    text = "I built it with React, Node.js, PostgreSQL, Redis and AWS."
    assert any("tech" in e for e in voice_errors(text, "answer"))


def test_voice_accepts_a_plain_impact_answer():
    text = (
        "I rebuilt the grading flow at OC Connect so instructors stopped exporting "
        "spreadsheets by hand. About 2K+ learners use it now. I picked Postgres and "
        "Node.js because the team already ran them."
    )
    assert voice_errors(text, "answer") == []


def test_voice_flags_three_tool_lists_too():
    # The first regenerated SerpApi letter still read "JavaScript, Python, and Go".
    assert voice_errors("I ship across JavaScript, Python, and Go.", "letter")
    assert voice_errors("I built backends in NestJS, FastAPI and Node.js.", "letter")


def test_voice_allows_plain_word_lists():
    assert voice_errors("Scraping, parsing, and keeping up with layouts is hard.", "letter") == []
