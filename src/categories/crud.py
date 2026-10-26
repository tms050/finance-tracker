"""CRUD категорий."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src._internal.sentinel import UNSET, _UnsetType
from src.db import Category, Transaction

from src.db.constants import CATEGORY_TYPES

CategoryType = Literal["income", "expense", "transfer"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_category_by_name_and_parent(
    session: Session, name: str, parent_id: int | None
) -> Category | None:
    return session.execute(
        select(Category).where(
            Category.name == name,
            Category.parent_category_id == parent_id,
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_category(session: Session, category_id: int) -> Category | None:
    """None если не найдена."""
    return session.get(Category, category_id)


def list_categories(
    session: Session,
    *,
    parent_id: int | None | _UnsetType = UNSET,
    type: CategoryType | None = None,
) -> list[Category]:
    """Список категорий.

    Args:
        parent_id:
            UNSET - все категории;
            None - только корневые (parent_category_id IS NULL);
            int - только дети указанного родителя.
        type: фильтр по типу (income / expense / transfer).

    Сортировка: name ASC, category_id ASC.
    """
    stmt = select(Category)
    if not isinstance(parent_id, _UnsetType):
        if parent_id is None:
            stmt = stmt.where(Category.parent_category_id.is_(None))
        else:
            stmt = stmt.where(Category.parent_category_id == parent_id)
    if type is not None:
        stmt = stmt.where(Category.type == type)
    stmt = stmt.order_by(Category.name.asc(), Category.category_id.asc())
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Create / rename / delete
# ---------------------------------------------------------------------------

def create_category(
    session: Session,
    name: str,
    category_type: CategoryType,
    parent_id: int | None = None,
) -> Category:
    """Создать категорию. ValueError, если (name, parent_id) уже есть."""

    if category_type not in CATEGORY_TYPES:
        raise ValueError(
            f"category_type must be one of {CATEGORY_TYPES}, "
            f"got {category_type!r}"
        )

    name = (name or "").strip()
    if not name:
        raise ValueError("category name must be non-empty")

    if _get_category_by_name_and_parent(session, name, parent_id) is not None:
        raise ValueError(
            f"category with name={name!r} and parent_id={parent_id} "
            f"already exists"
        )

    category = Category(
        name=name,
        type=category_type,
        parent_category_id=parent_id,
    )
    session.add(category)
    session.flush()
    return category


def rename_category(
    session: Session,
    category_id: int,
    new_name: str,
) -> Category:
    """Переименовать. ValueError на дубль/несуществующий id."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("category name must be non-empty")

    category = session.get(Category, category_id)
    if category is None:
        raise ValueError(f"category with id={category_id} not found")

    conflict = session.execute(
        select(Category).where(
            Category.name == new_name,
            Category.parent_category_id == category.parent_category_id,
            Category.category_id != category_id,
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise ValueError(
            f"category with name={new_name!r} and parent_id="
            f"{category.parent_category_id} already exists"
        )

    category.name = new_name
    session.flush()
    return category


def delete_category(session: Session, category_id: int) -> None:
    """Удалить. Транзакции с category_id -> NULL (unlink).

    Категории-родители с детьми: поведение зависит от FK в БД
    (CASCADE / RESTRICT / SET NULL) - в B2b не управляем деревом.
    """
    category = session.get(Category, category_id)
    if category is None:
        raise ValueError(f"category with id={category_id} not found")

    session.execute(
        update(Transaction)
        .where(Transaction.category_id == category_id)
        .values(category_id=None),
        execution_options={"synchronize_session": False},
    )
    session.delete(category)
    session.flush()