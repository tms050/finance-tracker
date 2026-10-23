"""Создание/обновление схемы БД."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from src.db import models  # noqa: F401 — регистрирует таблицы в Base.metadata
from src.db.base import Base
from src.db.engine import get_engine
from src.db.migrations import init_fresh_schema, run_migrations


def init_db(engine: Engine | None = None) -> None:
    """Создать схему (свежая БД) или применить миграции (существующая).

    Свежая БД: create_all() создаёт таблицы с актуальной схемой,
    затем пишется CURRENT_SCHEMA_VERSION в schema_version.

    Существующая БД: create_all() не вызывается, чтобы не мешать
    миграциям (они сами создают новые колонки/индексы).
    """
    engine = engine or get_engine()
    table_names = set(inspect(engine).get_table_names())

    if "schema_version" not in table_names:
        Base.metadata.create_all(bind=engine)
        init_fresh_schema(engine)
    else:
        run_migrations(engine)