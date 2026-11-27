"""The runner and agent step suites, rerun with the dossiers and the pipeline store on
one SQL backend (SQLite), the way production shares one Postgres backend."""
import pytest

from app import doc_store, job_store
from app.pipeline import store

from tests import test_pipeline_agents as agents_suite
from tests import test_pipeline_leases as leases_suite
from tests import test_pipeline_runner as runner_suite


@pytest.fixture(autouse=True)
def sql_backend(monkeypatch, tmp_path):
    backend = doc_store.SqlBackend(f"sqlite:///{tmp_path / 'pipeline.db'}")
    monkeypatch.setattr(job_store, "_BACKEND_OVERRIDE", backend)
    monkeypatch.setattr(store, "_BACKEND_OVERRIDE", backend)
    return backend


for _module in (runner_suite, agents_suite, leases_suite):
    for _name in dir(_module):
        if _name.startswith("test_"):
            globals()[f"{_name}_on_sql"] = getattr(_module, _name)
