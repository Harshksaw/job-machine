"""One module per outside job feed. Each stages finds in research_store and nothing else.

A source owns its client, its rate limits and its mapping to a research item, and imports
only job_store (to flag already tracked roles) and research_store. Nothing here creates
dossiers: fit scoring and capture stay agent steps (AGENTS.md).
"""
