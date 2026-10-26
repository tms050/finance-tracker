# tests/db/conftest.py
"""Общие фикстуры для тестов БД.

ВАЖНО: используется in-memory SQLite через StaticPool - все сессии в рамках одного теста видят одну и ту же БД

"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db import engine as _db_engine_module  # noqa: F401
from src.db import models as _models  # noqa: F401
from src.db.init import init_db


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """Свежая in-memory SQLite с актуальной схемой (init_db -> create_all)."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        init_db(eng)
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Явная фабрика - тесты, которым нужен контроль над сессиями."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Короткоживущая сессия.

    На teardown - явный rollback (не полагаемся на неявный в close()):
    если тест упал посреди транзакции, состояние должно быть отброшено до dispose() движка.
    """
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()