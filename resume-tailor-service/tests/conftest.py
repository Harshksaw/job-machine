import os

import pytest

# app/main.py calls load_dotenv() on import, and `neon env pull` writes the real
# Neon URLs into .env. Without this, importing the app in a test would point every
# store at the production database. Tests choose a backend explicitly instead.
_DATABASE_VARS = ("DATABASE_URL", "DATABASE_URL_UNPOOLED")



# The same .env carries the Langfuse keys, and telemetry is set up when the app is
# imported. load_dotenv never overrides a variable that is already set, so blanking
# these keeps test spans out of the real Langfuse project.
_EXPORTER_VARS = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)


def pytest_configure(config):
    for name in _DATABASE_VARS:
        os.environ.pop(name, None)
    # A PIPELINE_WORKERS in .env would start the worker pool in any test that enters
    # the app lifespan.
    os.environ.pop("PIPELINE_WORKERS", None)
    for name in _EXPORTER_VARS:
        os.environ[name] = ""


@pytest.fixture(autouse=True)
def no_database_url(monkeypatch):
    for name in _DATABASE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("PIPELINE_WORKERS", raising=False)
