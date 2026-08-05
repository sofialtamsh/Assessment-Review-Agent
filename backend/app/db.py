"""SQLite engine + session helpers (SQLModel)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
_db_url = _settings.db_url
_is_sqlite = _db_url.startswith("sqlite")
# Resilience for free hosted Postgres (e.g. Neon) which SUSPENDS when idle:
#   * pool_pre_ping  -> test a connection before use; transparently replace a dead one
#   * pool_recycle   -> drop connections older than 5 min (the provider closes idle ones)
#   * connect_timeout-> fail a wake attempt fast so it retries instead of hanging
# check_same_thread is SQLite-only.
if _is_sqlite:
    engine = create_engine(_db_url, echo=False, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        _db_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    )


# Columns added after the first release. SQLite's create_all won't add columns to
# an existing table, so we ALTER-add any that are missing (self-healing migration).
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "sessions": {
        "owner": "TEXT DEFAULT ''",
        "content_parsed": "BOOLEAN DEFAULT 0",
        "tutorial_url": "TEXT",
        "mcq_doc_url": "TEXT",
        "quiz_doc_url": "TEXT",
        "prepared_sets": "JSON",
        "rubric_text": "TEXT",
        "rubric_criteria": "JSON",
        "rubric_source": "TEXT",
    },
    "findings": {
        "related_ids": "JSON",
    },
    "runs": {
        "reviewer": "TEXT DEFAULT ''",
    },
}


def init_db() -> None:
    # Import models so their tables register on SQLModel.metadata before create_all.
    import time

    from . import models  # noqa: F401

    # A suspended Neon DB may take a few seconds to wake on the first connection at
    # startup — retry briefly so the app doesn't crash-loop instead of waiting.
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            SQLModel.metadata.create_all(engine)
            _ensure_columns()
            return
        except Exception as e:  # noqa: BLE001 - DB waking; retry a few times
            last_err = e
            time.sleep(2)
    if last_err:
        raise last_err


def _ensure_columns() -> None:
    # The self-healing shim below uses SQLite-specific PRAGMA/ALTER. On Postgres,
    # create_all() already builds complete tables, so there's nothing to back-fill.
    if not _is_sqlite:
        return

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if not existing:
                continue  # table doesn't exist yet (fresh create_all already made it)
            for col, decl in columns.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
