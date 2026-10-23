"""Лёгкий механизм миграций схемы SQLite.
Идея:
  - Таблица schema_version хранит применённые версии.
  - MIGRATIONS - реестр функций {version: callable}.
  - run_migrations() применяет всё, что новее текущей версии.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

# Текущая версия схемы. Увеличивайте при каждом изменении models.py.
CURRENT_SCHEMA_VERSION: int = 1

# Реестр миграций: {версия_назначения: функция}.
# Пример для будущего: {2: _migrate_to_v2, 3: _migrate_to_v3}
MIGRATIONS: dict[int, Callable[[Connection], None]] = {}


def _ensure_version_table(engine: Engine) -> None:
    """Создать schema_version, если её нет (идемпотентно)."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))


def _get_current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        ).scalar_one()


def _record_version(conn: Connection, version: int) -> None:
    conn.execute(
        text("INSERT INTO schema_version (version) VALUES (:v)"),
        {"v": version},
    )


def init_fresh_schema(engine: Engine) -> None:
    """Для свежей БД: записать CURRENT_SCHEMA_VERSION после create_all()."""
    _ensure_version_table(engine)
    with engine.begin() as conn:
        _record_version(conn, CURRENT_SCHEMA_VERSION)


def run_migrations(engine: Engine) -> None:
    """Применить все неприменённые миграции до CURRENT_SCHEMA_VERSION.
    Каждая миграция + запись версии - в одной транзакции.
    Если миграция упала, БД не остаётся в промежуточном состоянии.
    """
    _ensure_version_table(engine)
    current = _get_current_version(engine)

    if current > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"БД новее кода: schema_version={current}, "
            f"code supports up to {CURRENT_SCHEMA_VERSION}. "
            f"Обновите приложение."
        )

    if current == CURRENT_SCHEMA_VERSION:
        return

    for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(
                f"Нет миграции для версии {version}. "
                f"Добавьте её в MIGRATIONS."
            )
        with engine.begin() as conn:
            migration(conn)
            _record_version(conn, version)


def get_schema_version(engine: Engine) -> int:
    """Публичный хелпер: узнать текущую версию схемы (для логов/дебага)."""
    _ensure_version_table(engine)
    return _get_current_version(engine)