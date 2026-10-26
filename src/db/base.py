"""Корневой DeclarativeBase и общие миксины для всех моделей."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс. Вся регистрация моделей идёт через Base.metadata."""


class TimestampMixin:
    """Миксин с полями created_at / updated_at.
    server_default=func.now() - время выставляет СУБД.
    onupdate=func.now() - SQLAlchemy подставит NOW() при UPDATE.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )