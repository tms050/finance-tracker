"""Создание/обновление схемы БД."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from src.db import models  # noqa: F401 - регистрирует таблицы в Base.metadata
from src.db.base import Base
from src.db.engine import get_engine
from src.db.migrations import init_fresh_schema, run_migrations


def init_db(engine: Engine | None = None) -> None:
    """Создать схему или применить миграции
    Создать схему: create_all() создаёт таблицы с актуальной схемой,
    затем пишется CURRENT_SCHEMA_VERSION в schema_version.

    Применить миграцию: create_all() не вызывается, чтобы не мешать
    миграциям.
    """
    engine = engine or get_engine()
    table_names = set(inspect(engine).get_table_names())
    has_version_table = "schema_version" in table_names
    has_transactions  = "transactions" in table_names

    if not has_version_table and not has_transactions:
        Base.metadata.create_all(bind=engine)
        init_fresh_schema(engine)
    elif not has_version_table and has_transactions:
        raise RuntimeError(
            "existing DB without schema_version table - "
            "manual migration required"
        )
    else:
        run_migrations(engine)