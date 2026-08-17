"""Shared fact-traceability vocabulary for the two validators.

`application_kit.validate_kit` (cover letters, answers) and
`validate.validate_manifest` (tailored-resume summaries) both ask the same
question: does this token trace back to something the resume bank actually
says? They used to answer it with two independent implementations, and the
tailoring side never received the fixes the kit side accumulated. The result
was a validator that rejected "Node" while the bank said "Node.js", failing
honest resumes. Both now share this module so a fix lands once.

Anti-fabrication is unchanged: this widens only synonyms, plurals and
sub-parts of terms the bank already contains. A term the bank never mentions
is still untraceable.
"""
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#\-]*")

# Vocabulary shared by every engineering job posting on earth. Naming "API" or
# "GPU" claims no credential, so demanding a bank source for it rejected
# otherwise perfect output (observed live on 2026-08-13). Deliberately
# excluded: nameable skills and products such as SQL, HTML, CSS, JWT, SSO and
# RBAC. Those ARE credential claims, and they stay traceable so a fabricated
# skill is still caught.
GENERIC_TECH_TERMS = {
    "ui", "ux", "api", "apis", "rest", "restful", "crud", "json", "xml",
    "http", "https", "url", "urls", "sdk", "cli", "ide", "os", "qa", "mvp",
    "saas", "b2b", "b2c", "pr", "prs", "oop", "tdd", "etl", "sla", "mvc",
    "cpu", "gpu", "ram", "uuid", "csv", "pdf", "e2e", "poc",
    "iot", "jd", "llm", "llms", "ci", "cd",
    # Concepts, roles, compliance regimes and business terms. None of these is
    # a technology the candidate could claim to have used, so none is a
    # credential -- but each is an all-caps token `extract_facts` would
    # otherwise demand a source for.
    "oss", "sre", "dx", "pii", "gdpr", "soc", "hipaa",
    "kpi", "kpis", "okr", "okrs", "arr", "crm", "erp", "spa", "pwa", "sdlc",
    # Field and credential shorthand a job description uses to describe what it
    # wants ("CS degree or equivalent"). Restating the requirement is not
    # claiming a credential -- the degree the candidate actually holds is a
    # separate, still-traceable fact.
    "cs", "ee", "bs", "ba", "ms", "msc", "bsc", "phd", "stem", "it", "hr",
}
FACT_STOPWORDS = {"i"} | GENERIC_TECH_TERMS

MONTH_ALIASES = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november",
    "dec": "december",
}

# Equivalent names for one product. Strictly synonyms, never a different
# technology, so this cannot let a fabricated skill through.
TECH_ALIASES = {
    "postgresql": ("postgres",),
    "postgres": ("postgresql",),
    "mongodb": ("mongo",),
    "mongo": ("mongodb",),
    "kubernetes": ("k8s",),
    "k8s": ("kubernetes",),
    "javascript": ("js",),
    "typescript": ("ts",),
}


def singularize(word: str) -> str:
    """Crude English plural stripper, applied only when comparing a fact to
    already-allowed vocabulary.

    The bank names a format once ("PDF, DOCX, and TXT documents") and prose
    naturally pluralises it ("PDFs"). That is the same fact, not a new one, but
    the literal set lookup called it untraceable and 502'd honest answers. Only
    the plural of a term the bank already contains becomes traceable, so this
    cannot admit a fabricated technology.
    """
    lowered = word.lower()
    if len(lowered) > 3 and lowered.endswith("ies"):
        return lowered[:-3] + "y"
    if len(lowered) > 2 and lowered.endswith("es") and lowered[-3:-2] in "sxzoh":
        return lowered[:-2]
    if len(lowered) > 2 and lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def allowed_tokens(text: str) -> set[str]:
    """Every token the given corpus makes traceable.

    Includes both whole tokens AND their "/"-, "-"- and "."-split sub-parts, so
    a bank compound like "CI/CD", "RAG-based" or "Qwik.js" also makes "ci",
    "cd", "rag", "based", "qwik", "js" traceable. Without splitting on "." too,
    a bank tech name stored in dotted form ("Qwik.js", "Node.js", "sync.Map")
    did not make its equally-truthful bare base name ("Qwik", "Node")
    traceable, so honest output failed validation and 502'd. The whole dotted
    token stays in the set as well, so exact dotted references ("Node.js") keep
    matching.
    """
    allowed: set[str] = set()
    for token in _TOKEN_RE.findall(text):
        allowed.add(token.lower())
        allowed.add(singularize(token))
        for part in re.split(r"[/.-]", token):
            if not part:
                continue
            allowed.add(part.lower())
            allowed.add(singularize(part))
            # The bank abbreviates months ("Dec 2026"); writing "December" is
            # the same fact, not a new one. The prompt asks for the ledger's
            # spelling and the model complies inconsistently, so accept both
            # rather than fail otherwise honest output.
            full = MONTH_ALIASES.get(part.lower())
            if full:
                allowed.add(full)
            # Same idea for tech names the bank stores in one canonical form:
            # "Postgres" and "PostgreSQL" are one product, not two facts, and
            # rejecting the short form failed honest letters.
            for alias in TECH_ALIASES.get(part.lower(), ()):
                allowed.add(alias)
                allowed.add(singularize(alias))
    return allowed


def _known(token: str, allowed: set[str]) -> bool:
    lowered = token.lower()
    if lowered in allowed or lowered in FACT_STOPWORDS:
        return True
    stem = singularize(token)
    return stem in allowed or stem in FACT_STOPWORDS


def literal_fact_is_traceable(fact: str, corpus_lower: str) -> bool:
    """Check a digit-bearing fact ("40K+", "H100s", "2026") against the corpus.

    These take a literal-substring path rather than the token path, because an
    invented figure must never slip through on a near-match. The one widening
    is the plural: the bank says "4x NVIDIA H100 GPUs" and prose naturally
    writes "H100s", which is the same fact. Only the plural of a string the
    corpus already contains becomes traceable, so a fabricated number is still
    caught -- "40K+" does not become traceable, because "40K" is absent too.
    """
    lowered = fact.lower()
    if lowered in corpus_lower:
        return True
    stem = singularize(fact)
    return stem != lowered and stem in corpus_lower


def fact_is_traceable(fact: str, allowed: set[str]) -> bool:
    if _known(fact, allowed):
        return True
    # Compound facts the model coins by gluing a bank term to a connective word
    # ("RAG-powered", "Bazel-driven", "CI/CD"): traceable only if EVERY acronym-
    # or proper-noun-like sub-part traces to the bank. Lowercase connectives
    # ("powered", "based", "driven") are not facts and are ignored, so a
    # genuinely fabricated Capitalized/acronym sub-part is still caught.
    # Split on "." as well, matching allowed_tokens. Without it "Express.js"
    # never decomposed into "Express" + "js", so a bank term stored bare
    # ("Express") could not cover its dotted form.
    parts = [p for p in re.split(r"[/.-]", fact) if p]
    if len(parts) < 2:
        return False
    for part in parts:
        significant = (
            (part.isupper() and len(part) >= 2)
            or part[:1].isupper()
            or any(c in ".+#" for c in part)
        )
        # Generic vocabulary is no more a credential inside a compound
        # ("GPU-level") than it is standing alone ("GPU").
        if significant and not _known(part, allowed):
            return False
    return True
