"""B2b: работа с категориями (автосоздание при импорте + CRUD)."""

from __future__ import annotations

import dataclasses
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import Category
from src.importing.import_to_db import (
    ImportResult,
    _find_existing_statement_id,
    import_prepared_statement,
)
from src.importing.prepare import PreparedStatement, PreparedTransaction

CategoryType = Literal["income", "expense", "transfer"]


# ---------------------------------------------------------------------------
# Автосоздание при импорте
# ---------------------------------------------------------------------------

def infer_category_type(
    amount: int | None,
    is_transfer: bool | None, 
) -> CategoryType:
    """is_transfer -> transfer; amount>0 -> income; amount<=0/None -> expense."""
    if bool(is_transfer):
        return "transfer"
    if amount is not None and amount > 0:
        return "income"
    return "expense"


def _get_category(
    session: Session,
    name: str,
    parent_id: int | None,
) -> Category | None:
    """Приватный хелпер: найти категорию по точному совпадению (name, parent_id)."""
    return session.execute(
        select(Category).where(
            Category.name == name,
            Category.parent_category_id == parent_id,
        )
    ).scalar_one_or_none()


def find_or_create_category(
    session: Session,
    name: str,
    category_type: CategoryType,
    parent_id: int | None = None,
) -> tuple[Category, bool, list[str]]:
    """Найти или создать категорию.

    Returns:
        (category, created, warnings)
        - created=True если создана; False если найдена.
        - warnings: непусто, если существующая категория имеет другой type.

    Ищет по (name, parent_id) - exact match, case-sensitive.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("category name must be non-empty")

    existing = _get_category(session, name, parent_id)

    if existing is not None:
        warnings: list[str] = []
        if existing.type != category_type:
            warnings.append(
                f"Категория «{name}» существует с типом '{existing.type}', "
                f"но встретилась транзакция с типом '{category_type}'. "
                f"Категория переиспользована; проверьте, что это ожидаемо."
            )
        return existing, False, warnings

    category = Category(
        name=name,
        type=category_type,
        parent_category_id=parent_id,
    )
    session.add(category)
    session.flush()
    return category, True, []


# ---------------------------------------------------------------------------
# Импорт с автосозданием категорий
# ---------------------------------------------------------------------------

def import_with_categories(
    session: Session,
    prepared: PreparedStatement,
    *,
    auto_create_categories: bool = True,
    chunk_size: int = 500,
) -> ImportResult:
    """B2a + автосоздание категорий по raw_category.

    - Dedup по file_hash проверяется до создания категорий.
    - auto_create_categories=False -> просто вызывает B2a.
    - Всё в одной транзакции (commit/rollback - забота вызывающего).
    """
    if prepared.account_id is None:
        raise ValueError(
            "prepared.account_id is None; B2b requires an explicit account_id "
            "(find_or_create_account - задача B2d)"
        )
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    existing_id = _find_existing_statement_id(session, prepared.file_hash)
    if existing_id is not None:
        return ImportResult(
            status="duplicate_statement",
            statement_id=existing_id,
        )

    if not auto_create_categories or not prepared.transactions_to_insert:
        return import_prepared_statement(
            session, prepared, chunk_size=chunk_size
        )

    inferred: dict[str, set[CategoryType]] = {}
    for p in prepared.transactions_to_insert:
        raw = (p.raw_category or "").strip()
        if not raw:
            continue
        inferred.setdefault(raw, set()).add(
            infer_category_type(p.amount, p.is_transfer)
        )

    cache: dict[str, Category] = {}
    created_ids: list[int] = []
    category_warnings: list[str] = []

    for raw in sorted(inferred.keys()):
        types = inferred[raw]
        if len(types) > 1:
            category_warnings.append(
                f"Категория «{raw}» в этой выписке встречается с разными "
                f"типами: {', '.join(sorted(types))}. "
                f"Использован '{sorted(types)[0]}'."
            )
        first_type = sorted(types)[0]  # 1. Теперь это CategoryType, а не str
        category, created, warns = find_or_create_category(
            session, raw, first_type, parent_id=None
        )
        cache[raw] = category
        if created:
            created_ids.append(category.category_id)
        category_warnings.extend(warns)

    new_txs: list[PreparedTransaction] = []
    for p in prepared.transactions_to_insert:
        raw = (p.raw_category or "").strip()
        if raw and raw in cache:
            new_txs.append(
                dataclasses.replace(p, category_id=cache[raw].category_id)
            )
        else:
            new_txs.append(p)
    new_prepared = dataclasses.replace(
        prepared, transactions_to_insert=tuple(new_txs)
    )

    b2a_result = import_prepared_statement(
        session, new_prepared, chunk_size=chunk_size
    )

    return dataclasses.replace(
        b2a_result,
        created_categories=tuple(created_ids),
        warnings=b2a_result.warnings + tuple(category_warnings),
    )