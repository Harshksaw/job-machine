"""Document storage behind the job, people and session stores.

Two backends share one small interface, so the stores keep their logic and only
swap where documents live:

- `JsonFileBackend` is the original layout: one JSON list per collection, read and
  rewritten whole under a process lock. It stays the default so the test suite
  and CI need no database and no secrets.
- `SqlBackend` keeps one row per document (SQLite for tests, Postgres on Neon in
  production). A write touches only the row it changes, and indexed columns
  (`canonical_url`, `match_key`, `status`, a precomputed `summary`) answer dedupe and
  the Inbox list without loading every dossier: jobs.json had reached 27 MB.

Writes run inside `transaction()`. On Postgres each write transaction also takes
a per-collection advisory lock, so two copies of the service (an agent sandbox
starting its own uvicorn, for instance) cannot interleave a read-modify-write.
Transactions are re-entrant per thread, so `capture_job` can wrap `add_job` or
`update_job` in one atomic unit.

`DATABASE_URL` selects the SQL backend. A plain `postgresql://` URL, as Neon hands
it out, is mapped to the psycopg driver.
"""
from __future__ import annotations

import os
import threading
import zlib
from contextlib import contextmanager
from typing import Callable, Iterator

from sqlalchemy import (
    JSON,
    Column,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine

_JSON = JSON().with_variant(JSONB(), "postgresql")

metadata = MetaData()
documents = Table(
    "documents",
    metadata,
    Column("collection", String(32), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("doc", _JSON, nullable=False),
    Column("summary", _JSON, nullable=True),
    Column("canonical_url", String, nullable=True),
    Column("match_key", String, nullable=True),
    Column("status", String(32), nullable=True),
    Column("sort_key", String(64), nullable=True),
)
Index("documents_canonical_url", documents.c.collection, documents.c.canonical_url)
Index("documents_match_key", documents.c.collection, documents.c.match_key)
Index("documents_sort_key", documents.c.collection, documents.c.sort_key)

INDEX_FIELDS = ("summary", "canonical_url", "match_key", "status", "sort_key")


# ---------------------------------------------------------------------------
# JSON files (default)
# ---------------------------------------------------------------------------


class _JsonTransaction:
    def __init__(self, items: list[dict]):
        self.items = items
        self.dirty = False

    def get(self, doc_id: str) -> dict | None:
        return next((raw for raw in self.items if raw.get("id") == doc_id), None)

    def put(self, doc: dict, index: dict | None = None) -> None:
        for position, raw in enumerate(self.items):
            if raw.get("id") == doc["id"]:
                self.items[position] = doc
                break
        else:
            self.items.append(doc)
        self.dirty = True

    def delete(self, doc_id: str) -> bool:
        kept = [raw for raw in self.items if raw.get("id") != doc_id]
        if len(kept) == len(self.items):
            return False
        self.items[:] = kept
        self.dirty = True
        return True

    def all(self) -> list[dict]:
        return list(self.items)


class JsonFileBackend:
    """Whole-file JSON lists. `read`/`write` are the owning store's own functions,
    so its error handling (refusing to overwrite a malformed file) is unchanged."""

    has_index = False

    def __init__(self, read: Callable[[], list[dict]], write: Callable[[list[dict]], None],
                 lock: threading.RLock):
        self._read = read
        self._write = write
        self._lock = lock
        self._local = threading.local()

    @contextmanager
    def transaction(self, collection: str) -> Iterator[_JsonTransaction]:
        with self._lock:
            current = getattr(self._local, "tx", None)
            if current is not None:
                yield current
                return
            tx = _JsonTransaction(self._read())
            self._local.tx = tx
            try:
                yield tx
                if tx.dirty:
                    self._write(tx.items)
            finally:
                self._local.tx = None

    def all(self, collection: str) -> list[dict]:
        with self.transaction(collection) as tx:
            return tx.all()

    def get(self, collection: str, doc_id: str) -> dict | None:
        with self.transaction(collection) as tx:
            return tx.get(doc_id)


# ---------------------------------------------------------------------------
# SQL (SQLite in tests, Postgres on Neon)
# ---------------------------------------------------------------------------


def sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class _SqlTransaction:
    def __init__(self, conn: Connection, collection: str):
        self.conn = conn
        self.collection = collection

    def _where(self, doc_id: str):
        return (documents.c.collection == self.collection) & (documents.c.id == doc_id)

    def get(self, doc_id: str) -> dict | None:
        query = select(documents.c.doc).where(self._where(doc_id))
        if self.conn.dialect.name == "postgresql":
            query = query.with_for_update()
        return self.conn.execute(query).scalar_one_or_none()

    def put(self, doc: dict, index: dict | None = None) -> None:
        index = index or {}
        values = {field: index.get(field) for field in INDEX_FIELDS}
        values["doc"] = doc
        exists = self.conn.execute(
            select(documents.c.id).where(self._where(doc["id"]))
        ).first()
        if exists:
            self.conn.execute(documents.update().where(self._where(doc["id"])).values(**values))
        else:
            self.conn.execute(
                documents.insert().values(collection=self.collection, id=doc["id"], **values)
            )

    def delete(self, doc_id: str) -> bool:
        return self.conn.execute(delete(documents).where(self._where(doc_id))).rowcount > 0

    def all(self) -> list[dict]:
        return list(
            self.conn.execute(
                select(documents.c.doc)
                .where(documents.c.collection == self.collection)
                .order_by(documents.c.sort_key)
            ).scalars()
        )


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SqlBackend:
    has_index = True

    def __init__(self, url: str, *, engine: Engine | None = None):
        url = sqlalchemy_url(url)
        # prepare_threshold=None: psycopg's automatic prepared statements break
        # behind Neon's PgBouncer (transaction mode) if the pooled URL is used.
        connect_args = {"prepare_threshold": None} if url.startswith("postgresql") else {}
        self.engine = engine or create_engine(
            url, pool_pre_ping=True, connect_args=connect_args
        )
        metadata.create_all(self.engine)
        self._local = threading.local()
        # SQLite has no row locks; serialize writers in-process so tests and a
        # local file behave the way Postgres does across processes.
        self._sqlite_lock = threading.RLock() if self.engine.dialect.name == "sqlite" else None

    @contextmanager
    def transaction(self, collection: str) -> Iterator[_SqlTransaction]:
        current = getattr(self._local, "tx", None)
        if current is not None:
            yield current
            return
        with self._sqlite_lock or _NullLock(), self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                key = zlib.crc32(collection.encode("utf-8"))
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            tx = _SqlTransaction(conn, collection)
            self._local.tx = tx
            try:
                yield tx
            finally:
                self._local.tx = None

    def all(self, collection: str) -> list[dict]:
        with self.transaction(collection) as tx:
            return tx.all()

    def get(self, collection: str, doc_id: str) -> dict | None:
        with self.transaction(collection) as tx:
            return tx.get(doc_id)

    def find(self, collection: str, field: str, value: str) -> list[dict]:
        """Documents whose indexed `field` equals `value`, newest first."""
        with self.transaction(collection) as tx:
            return list(
                tx.conn.execute(
                    select(documents.c.doc)
                    .where((documents.c.collection == collection) & (documents.c[field] == value))
                    .order_by(documents.c.sort_key.desc())
                ).scalars()
            )

    def index_values(self, collection: str, field: str) -> list:
        """One indexed column for the whole collection, newest first."""
        with self.transaction(collection) as tx:
            return list(
                tx.conn.execute(
                    select(documents.c[field])
                    .where(documents.c.collection == collection)
                    .order_by(documents.c.sort_key.desc())
                ).scalars()
            )


_SQL_BACKENDS: dict[str, SqlBackend] = {}


def database_url_from_env() -> str:
    """Neon's direct URL first: this is a long-running server, and the direct
    connection keeps session behaviour that PgBouncer's transaction pooling drops.
    `neon env pull` writes it as DATABASE_URL_UNPOOLED next to DATABASE_URL."""
    return (
        os.environ.get("DATABASE_URL_UNPOOLED", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )


def sql_backend_from_env() -> SqlBackend | None:
    """The shared SQL backend when a database URL is set, else None (JSON files)."""
    url = database_url_from_env()
    if not url:
        return None
    if url not in _SQL_BACKENDS:
        _SQL_BACKENDS[url] = SqlBackend(url)
    return _SQL_BACKENDS[url]
