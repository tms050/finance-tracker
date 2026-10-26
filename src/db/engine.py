"""Создание Engine для SQLite + настройка PRAGMA.

SQLite по умолчанию:
  - Не выполняет ON DELETE CASCADE / SET NULL (foreign_keys=OFF);
  - использует journal_mode=DELETE, что блокирует читателей при записи;
  - падает с 'database is locked' при конкуренции без busy_timeout.
Слушатель события "connect" применяет нужные настройки на каждом соединении.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

DEFAULT_DB_PATH = "data/db/finance.db"


def _resolve_db_path() -> Path:
    raw = os.getenv("FINANCE_DB_PATH", DEFAULT_DB_PATH)
    path = Path(raw).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def make_engine(db_url: str | None = None, *, echo: bool = False) -> Engine:
    """Создаёт Engine. db_url=None - взять путь из env с фолбэком."""
    if db_url is None:
        db_url = f"sqlite:///{_resolve_db_path()}"
    return create_engine(
        db_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        # IMMEDIATE: транзакция сразу берёт write-lock,
        # что снижает риск дедлоков при конкурентной записи.
        connect_args={"isolation_level": "IMMEDIATE"},
    )


_engine: Engine | None = None


def get_engine() -> Engine:
    """Вернуть глобальный Engine, создав его при первом вызове."""
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


@event.listens_for(Engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.fetchone()
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

        # Unicode-aware lower() для корректного ILIKE на кириллице
        # SQLite built-in lower() поддерживает только ASCII
        # Регистрируем python str.lower() - он Unicode-aware
        dbapi_connection.create_function(
            "lower", 1,
            lambda s: s.lower() if isinstance(s, str) else s,
            deterministic=True,
        )