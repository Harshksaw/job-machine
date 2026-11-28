"""Where a remote role may be held from, and which tier that puts it in.

Policy (AGENTS.md, search policy): remote roles are worked in country order Canada, US,
UK, Australia, New Zealand, any other country, Europe last. Nothing based in India.

    classify_location("US, Canada")      -> tier A,  region canada
    classify_location("United Kingdom")  -> tier A2, region uk
    classify_location("Germany")         -> tier E,  region europe
    classify_location("US, India")       -> tier drop, reason india

Tier A: open to Canada, or anywhere. Tier A2: limited to the US, UK, Australia, New Zealand
or another country outside India and Europe. Tier E: limited to Europe (EU, EEA,
Switzerland and the rest of geographic Europe outside the UK); kept, but last. India excludes a role even when another region also matches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    tier: str  # "A", "A2", "E" or "drop"
    region: str  # canada, worldwide, unspecified, us, uk, australia, new zealand, other, europe, ""
    reason: str = ""  # why it was dropped; empty when kept
    rank: int = 99  # country order: lower is worked first


# Lower rank is worked first. Tier A regions share rank 0.
RANK = {
    "canada": 0, "worldwide": 0, "unspecified": 0,
    "us": 1, "uk": 2, "australia": 3, "new zealand": 4, "other": 5, "europe": 6,
}

_INDIA = re.compile(
    r"\bindia\b|\bbengaluru\b|\bbangalore\b|\bmumbai\b|\bhyderabad\b|\bpune\b|\bdelhi\b|"
    r"\bchennai\b|\bgurgaon\b|\bgurugram\b|\bnoida\b|\bkolkata\b|\bahmedabad\b",
    re.I,
)
_NOT_REMOTE = re.compile(r"\bhybrid\b|\bon.?site\b|\bin.?office\b|\bin.person\b", re.I)

_CANADA = re.compile(
    r"\bcanada\b|\bcanadian\b|\bnorth america\b|\btoronto\b|\bvancouver\b|\bmontreal\b|\bcalgary\b|\bottawa\b|"
    r"(?<!latin )(?<!south )(?<!central )\bamericas\b",
    re.I,
)
_WORLDWIDE = re.compile(r"\bworld.?wide\b|\banywhere\b|\bglobal(ly)?\b|\bworld\b", re.I)
# Strict: uppercase "US" only, so prose such as "work with us" never reads as the US.
_US_CASED = re.compile(r"(?<![A-Za-z])US(?![A-Za-z])")
_US = re.compile(
    r"\bunited states\b|\busa\b|(?<![a-z])u\.s\.(a\.?)?|"
    r"(?<!north )(?<!latin )(?<!south )(?<!central )\bamerica\b(?!s)",
    re.I,
)
_UK = re.compile(
    r"\bunited kingdom\b|\buk\b|\bu\.k\.|\bgreat britain\b|\bbritain\b|\bengland\b|"
    r"\bscotland\b|\bwales\b|\bnorthern ireland\b|\blondon\b",
    re.I,
)
_AUSTRALIA = re.compile(r"\baustralia\b|\baustralian\b|\banz\b|\bsydney\b|\bmelbourne\b", re.I)
_NEW_ZEALAND = re.compile(r"\bnew zealand\b|\bnz\b|\baotearoa\b|\bauckland\b|\bwellington\b", re.I)
_OTHER = re.compile(
    r"\blatam\b|\blatin america\b|\bsouth america\b|\bcentral america\b|\bapac\b|\basia\b|"
    r"\bafrica\b|\bmiddle east\b",
    re.I,
)
# EU 27, EEA (Iceland, Liechtenstein, Norway), Switzerland and the rest of geographic Europe
# outside the UK (Balkans, Ukraine, Moldova, microstates), plus the usual region words and
# big tech cities. The UK is not here: it is Tier A2. "Ireland" only when not
# "Northern Ireland", which is the UK.
_EUROPE = re.compile(
    r"\beurope\b|\beuropean\b|\beu\b|\beea\b|\bemea\b|\bschengen\b|\bcet\b|\bcest\b|"
    r"\baustria\b|\bbelgium\b|\bbulgaria\b|\bcroatia\b|\bcyprus\b|\bczech republic\b|\bczechia\b|"
    r"\bdenmark\b|\bestonia\b|\bfinland\b|\bfrance\b|\bgermany\b|\bdeutschland\b|\bgreece\b|"
    r"\bhungary\b|(?<!northern )\bireland\b|\bitaly\b|\blatvia\b|\blithuania\b|\bluxembourg\b|"
    r"\bmalta\b|\bnetherlands\b|\bholland\b|\bpoland\b|\bportugal\b|\bromania\b|\bslovakia\b|"
    r"\bslovenia\b|\bspain\b|\bsweden\b|\biceland\b|\bliechtenstein\b|\bnorway\b|"
    r"\bswitzerland\b|\bberlin\b|\bmunich\b|\bparis\b|\bamsterdam\b|\bmadrid\b|\bbarcelona\b|"
    r"\blisbon\b|\bdublin\b|\bwarsaw\b|\bstockholm\b|\bcopenhagen\b|\bzurich\b|\bvienna\b|"
    r"\bprague\b|\balbania\b|\bandorra\b|\bbelarus\b|\bbosnia\b|\bherzegovina\b|\bkosovo\b|"
    r"\bmoldova\b|\bmonaco\b|\bmontenegro\b|\bmacedonia\b|\bsan marino\b|\bserbia\b|"
    r"\bukraine\b|\bvatican\b|\bbelgrade\b|\bkyiv\b|\bkiev\b|\bsarajevo\b|\btirana\b|"
    r"\bskopje\b|\bchisinau\b|\bpodgorica\b|\blviv\b|\bnovi sad\b",
    re.I,
)
# Words that carry no place, so "Remote" or "Remote - " alone reads as unspecified.
_FILLER = re.compile(
    r"\bremote\b|\bonly\b|\bbased\b|\bfully\b|\bfirst\b|\bjob\b|\btime ?zones?\b|[^a-z]+", re.I
)


# Where the company itself is based, read from the job description: "headquartered in X",
# "HQ is in X", "based in X", "X-based". Only the first place in the phrase counts.
_BASE_IN = re.compile(
    r"\b(?:headquartered|headquarters|hq|based|located)\s+(?:(?:is|are)\s+)?(?:in|out of)\s+"
    r"(?:the\s+)?(?P<place>[^.,;:\n()]{1,60})",
    re.I,
)
_PLACE_BASED = re.compile(r"\b(?P<place>[a-z]+(?: [a-z]+)?)[ -]based\b", re.I)


def company_base(description: str | None) -> str:
    """'india' or 'europe' when the description says the company is based there, else ''."""
    for pattern in (_BASE_IN, _PLACE_BASED):
        for match in pattern.finditer(description or ""):
            place = re.split(r"\s+(?:and|or|with|but)\s+", match.group("place"), maxsplit=1)[0]
            if is_india(place):
                return "india"
            if _EUROPE.search(place) and not _UK.search(place):
                return "europe"
    return ""


def is_india(text: str | None) -> bool:
    """True when the text names India or a major Indian city. 'Indiana' is not India."""
    return bool(_INDIA.search(text or ""))


def _drop(reason: str) -> Classification:
    return Classification("drop", "", reason, RANK.get("drop", 99))


def _kept(tier: str, region: str) -> Classification:
    return Classification(tier, region, "", RANK[region])


def classify_location(location: str, remote_scope: str = "", *, description: str = "") -> Classification:
    """Tier a remote listing from its location text and optional remote scope.

    `description` (the job description) is read only for where the company is based: an
    India based company is dropped, a European company drops to Tier E.
    """
    where = _classify_place(location, remote_scope)
    if where.tier == "drop":
        return where
    base = company_base(description)
    if base == "india":
        return _drop("india")
    if base == "europe" and where.tier in ("A", "A2"):
        return _kept("E", "europe")
    return where


# "excluding Canada", "except India", "not open to Canada": the places named up to the next
# comma or full stop are carved out, never read as where the role may be held from.
_EXCLUDED = re.compile(
    r"\b(?:exclud(?:e|es|ed|ing)|except(?:\s+for)?|not\s+(?:open\s+to|available\s+(?:in|to)|in))\s+"
    r"(?P<places>[^.,;()]*)",
    re.I,
)
# A work authorization clause ties "worldwide" to whichever country it names.
_WORK_AUTH = re.compile(
    r"work authori[sz]ation|work permit|right to work|authori[sz]ed to work|eligible to work", re.I
)


def _classify_place(location: str, remote_scope: str) -> Classification:
    text = " ".join(part.strip() for part in (location or "", remote_scope or "") if part and part.strip())
    excluded = " ".join(match.group("places") for match in _EXCLUDED.finditer(text))
    text = _EXCLUDED.sub(" ", text)
    no_canada = bool(_CANADA.search(excluded))
    if is_india(text):
        return _drop("india")
    if _NOT_REMOTE.search(text):
        return _drop("not remote")
    if _CANADA.search(text):
        return _kept("A", "canada")
    worldwide = bool(_WORLDWIDE.search(text))
    if worldwide and not no_canada and not _WORK_AUTH.search(text):
        return _kept("A", "worldwide")
    if _US_CASED.search(text) or _US.search(text):
        return _kept("A2", "us")
    if _UK.search(text):
        return _kept("A2", "uk")
    if _AUSTRALIA.search(text):
        return _kept("A2", "australia")
    if _NEW_ZEALAND.search(text):
        return _kept("A2", "new zealand")
    if _OTHER.search(text):
        return _kept("A2", "other")
    if _EUROPE.search(text):
        return _kept("E", "europe")
    if no_canada:
        # Open elsewhere but Canada is carved out: never Tier A.
        return _kept("A2", "other")
    if worldwide:
        return _kept("A", "worldwide")
    if not _FILLER.sub("", text):
        return _kept("A", "unspecified")
    # A place we do not list (Brazil, Philippines, a city): another non India country.
    return _kept("A2", "other")


def open_to_canada(location: str, remote_scope: str = "") -> bool:
    """True when the place itself lets someone living in Canada take the role (Tier A by
    place alone; the company base does not change this fact)."""
    return _classify_place(location, remote_scope).tier == "A"


def tag_item(item: dict) -> Classification:
    """Set `tier`, `region` and `open_to_canada` on a research item from its `location`,
    `remote_scope` and `jd_text`. Returns the classification; tier "drop" means do not stage."""
    location, scope = item.get("location") or "", item.get("remote_scope") or ""
    where = classify_location(location, scope, description=item.get("jd_text") or "")
    item["tier"], item["region"] = where.tier, where.region
    item["open_to_canada"] = open_to_canada(location, scope)
    return where
