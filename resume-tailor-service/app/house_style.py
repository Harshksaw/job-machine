"""Harsh's writing rules, enforced on generated text instead of requested in prompts.

AGENTS.md bans em dashes and hyphenated compound words in anything he sends. The
model ignores the instruction often enough (the Socure kit on 2026-11-05 shipped
"human-in-the-loop" and "fault-tolerant") that it is applied here, on output.

Two steps, because they run at different points:

- `strip_dashes` is safe before validation. It only swaps punctuation, so every
  fact token the traceability check reads is unchanged.
- `unhyphenate` runs after validation. It rewrites tokens ("multi-tenant" becomes
  "multitenant"), and the validator matches bank terms like "multi-tenant" whole.

Chunks that are identifiers rather than prose are left alone: anything with a
digit (H-1B, GPT-4, claude-haiku-4-5), a slash, an @, or a domain dot.
"""
import re

# Prefixes that read as one word once the hyphen goes ("cofounder", "nontrivial").
# Everything else becomes two words ("full stack", "human in the loop").
_JOINED_PREFIXES = {"co", "re", "pre", "non", "multi", "sub", "semi", "anti"}

_EN_DASH_RANGE = re.compile(r"(\d)\s*–\s*(\d)")
_DASH = re.compile(r"\s*(?:—|–|--)\s*")
_COMPOUND = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b")
_IDENTIFIER = re.compile(r"\d|/|@|\.[A-Za-z]")


def strip_dashes(text: str) -> str:
    text = _EN_DASH_RANGE.sub(r"\1 to \2", text)
    return _DASH.sub(", ", text)


def _unhyphenate_word(match: re.Match) -> str:
    parts = match.group(0).split("-")
    out = parts[0]
    for part in parts[1:]:
        joiner = "" if out.lower() in _JOINED_PREFIXES else " "
        out += joiner + part
    return out


def unhyphenate(text: str) -> str:
    chunks = re.split(r"(\s+)", text)
    return "".join(
        chunk if _IDENTIFIER.search(chunk) else _COMPOUND.sub(_unhyphenate_word, chunk)
        for chunk in chunks
    )


def apply_house_style(text: str) -> str:
    return unhyphenate(strip_dashes(text))
