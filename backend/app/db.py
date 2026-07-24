"""SQLite engine + session helpers (SQLModel)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    # Import models so their tables register on SQLModel.metadata before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
