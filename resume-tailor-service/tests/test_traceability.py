"""Rules shared by the cover-letter validator and the resume-summary validator.

The two live batch failures these lock down (2026-08-16):
  - tailoring: "untraceable fact in summary: 'Node'" while the bank says "Node.js"
  - answers:   "answer contains untraceable fact 'PDFs'" while the bank says "PDF"
"""
from app.traceability import (
    allowed_tokens,
    fact_is_traceable,
    literal_fact_is_traceable,
    singularize,
)

BANK = (
    "Shipped two production React Native apps with Node.js backends serving "
    "2K+ learners. Architected a multi-tenant RAG platform over PDF, DOCX and "
    "TXT documents, backed by PostgreSQL and deployed with Kubernetes CI/CD."
)


def _traceable(fact: str) -> bool:
    return fact_is_traceable(fact, allowed_tokens(BANK))


def test_dotted_bank_term_makes_its_bare_base_traceable():
    # The live tailoring failure: the bank stores "Node.js", the summary says
    # "Node", and that is the same fact.
    assert _traceable("Node")
    assert _traceable("Node.js")


def test_plural_of_a_bank_term_is_traceable():
    # The live answers failure: the bank names the format once ("PDF"), prose
    # pluralises it ("PDFs").
    assert _traceable("PDFs")
    assert _traceable("documents")


def test_tech_alias_is_traceable_in_both_directions():
    assert _traceable("Postgres")
    assert fact_is_traceable("PostgreSQL", allowed_tokens("Deployed Postgres."))
    assert fact_is_traceable("K8s", allowed_tokens("Ran Kubernetes in prod."))


def test_generic_vocabulary_needs_no_source():
    # Naming an API or a GPU claims no credential.
    assert fact_is_traceable("API", allowed_tokens("Wrote some code."))
    assert fact_is_traceable("GPUs", allowed_tokens("Wrote some code."))


def test_compound_of_bank_terms_is_traceable():
    assert _traceable("RAG-powered")
    assert _traceable("CI/CD")


def test_fabricated_technology_is_still_rejected():
    # The whole point of the validator. Widening synonyms and plurals must not
    # let a technology the bank never mentions through.
    assert not _traceable("Elasticsearch")
    assert not _traceable("Fortran")
    assert not _traceable("Cassandra")


def test_fabricated_subpart_of_a_compound_is_still_rejected():
    assert not _traceable("Cassandra-backed")
    assert not _traceable("Node/Erlang")


def test_plural_widening_does_not_invent_a_root():
    # "Cassandras" must not become traceable just because stripping the "s"
    # produces a token, and a bare "s"-ending word is not a licence to match.
    assert not _traceable("Cassandras")
    assert not _traceable("Redises")


def test_singularize_handles_common_shapes():
    assert singularize("PDFs") == "pdf"
    assert singularize("libraries") == "library"
    assert singularize("indexes") == "index"
    # Words that merely end in "ss" are not plurals.
    assert singularize("express") == "express"


def test_plural_of_a_digit_bearing_bank_term_is_traceable():
    # The bank says "4x NVIDIA H100 GPUs"; prose writes "H100s". Same fact.
    # Both callers pass an already-lowercased corpus, so the test does too.
    corpus = "trained on 4x nvidia h100 gpus across 26 intraday horizons"
    assert literal_fact_is_traceable("H100s", corpus)
    assert literal_fact_is_traceable("H100", corpus)


def test_invented_figures_are_still_rejected():
    # The whole point of the literal path. "30K+" and "12K+" must never add up
    # to a traceable "40K+", and a years-of-experience claim must be present.
    corpus = "30k+ users and a 12k+ user music platform; 2+ years of experience"
    assert not literal_fact_is_traceable("40K+", corpus)
    assert not literal_fact_is_traceable("3+", corpus)
    assert not literal_fact_is_traceable("500K+", corpus)
    assert literal_fact_is_traceable("30K+", corpus)
