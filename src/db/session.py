"""Фабрика сессий и контекстный менеджер get_session().

Публичный API: get_session() (short-lived) и make_session_factory(engine)
(для тестов / явной инъекции).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.engine import get_engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Ленивая фабрика, привязанная к переданному Engine.

    Основной сценарий - тесты: make_session_factory(test_engine).
    Для продакшена обычно не нужна: get_session() сам берёт get_engine().

    НЕ вызывать на import-time уровня модуля - только внутри функции/фикстуры.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def get_session() -> Iterator[Session]:
    """commit при успехе, rollback при исключении, close в finally.

    Первый вызов get_session() создаст Engine (и каталог БД, если путь ведёт в несуществующую директорию).

    Сессия короткоживущая: не хранить её между вызовами и не шарьте между потоками/задачами.
    """
    session = Session(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()