"""SQLAlchemy engine/session helpers and a small upsert utility.

Table definitions are reflected from the database: db/migrations is the only schema source.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Connection, Engine, MetaData, Table, create_engine, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from stockhub.common.settings import get_settings


def sqlalchemy_url(url: str) -> str:
    """Map a plain postgres URL (shared with dbmate and Next.js) to the psycopg 3 driver."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    raise ValueError("DATABASE_URL must start with postgresql:// or postgres://")


def make_engine(url: str, **kwargs: Any) -> Engine:
    kwargs.setdefault("pool_pre_ping", True)
    return create_engine(sqlalchemy_url(url), **kwargs)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide engine for DATABASE_URL."""
    return make_engine(get_settings().database_url)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """ORM session that commits on success and rolls back on error."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        yield session


_tables: dict[tuple[int, str], Table] = {}


def get_table(conn: Connection, name: str) -> Table:
    """Reflect (and cache per engine) a table definition."""
    key = (id(conn.engine), name)
    if key not in _tables:
        _tables[key] = Table(name, MetaData(), autoload_with=conn)
    return _tables[key]


def upsert(
    conn: Connection,
    table: str | Table,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
    update_cols: Sequence[str] | None = None,
) -> int:
    """INSERT ... ON CONFLICT for idempotent writes; returns the number of rows written.

    `update_cols=None` updates every non-key column present in the rows; an empty list
    means "insert if missing, otherwise leave untouched" (DO NOTHING).
    Rows whose values are unchanged are skipped and not counted.
    """
    if not rows:
        return 0
    tbl = get_table(conn, table) if isinstance(table, str) else table
    stmt = insert(tbl).values(list(rows))
    if update_cols is None:
        update_cols = [c for c in rows[0] if c not in conflict_cols]
    if not update_cols:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(conflict_cols))
    else:
        changed = [tbl.c[c].is_distinct_from(stmt.excluded[c]) for c in update_cols]
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={c: stmt.excluded[c] for c in update_cols},
            where=or_(*changed),
        )
    # rowcount is unreliable for multi-row inserts; count RETURNING rows instead.
    return len(conn.execute(stmt.returning(literal_column("1"))).all())
