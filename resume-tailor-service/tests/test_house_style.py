import pytest

from app.house_style import apply_house_style


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
