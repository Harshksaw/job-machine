import os

import pytest

# app/main.py calls load_dotenv() on import, and `neon env pull` writes the real
# Neon URLs into .env. Without this, importing the app in a test would point every
# store at the production database. Tests choose a backend explicitly instead.
_DATABASE_VARS = ("DATABASE_URL", "DATABASE_URL_UNPOOLED")


def pytest_configure(config):
    for name in _DATABASE_VARS:
        os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def no_database_url(monkeypatch):
    for name in _DATABASE_VARS:
        monkeypatch.delenv(name, raising=False)
