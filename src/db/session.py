"""Фабрика сессий и контекстный менеджер get_session()."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker

from src.db.engine import get_engine

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=get_engine(),
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def get_session() -> Iterator[Session]:
    """commit при успехе, rollback при исключении, close в finally."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()