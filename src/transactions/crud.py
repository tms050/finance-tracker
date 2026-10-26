"""B2c: CRUD для транзакций (ручное добавление, редактирование, удаление, чтение).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from src.db import Account, Category, Transaction
from src.importing.prepare import prepare_transaction

from src._internal.sentinel import UNSET, _UnsetType

from src.db.constants import TRANSACTION_CURRENCIES


class DuplicateTransactionError(ValueError):
    """Транзакция с таким (account_id, transaction_hash) уже есть."""

    def __init__(
        self,
        message: str,
        *,
        existing_transaction_id: int,
        transaction_hash: str,
    ) -> None:
        super().__init__(message)
        self.existing_transaction_id = existing_transaction_id
        self.transaction_hash = transaction_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_transaction_or_raise(
    session: Session, transaction_id: int
) -> Transaction:
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        raise ValueError(f"transaction with id={transaction_id} not found")
    return tx


def _validate_category_id(
    session: Session, category_id: int | None
) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise ValueError(f"category with id={category_id} not found")


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_transaction(
    session: Session,
    transaction_id: int,
    *,
    category_id: int | None | _UnsetType = UNSET,
    description: str | _UnsetType = UNSET,
    counterparty_name: str | None | _UnsetType = UNSET,
    is_transfer: bool | _UnsetType = UNSET,
) -> Transaction:
    """Частичное обновление. Меняются только переданные поля.

    Raises:
        ValueError: транзакция не найдена; category_id не существует.

    Редактируемые: category_id, description, counterparty_name, is_transfer.
    НЕ редактируемые в B2c: date, time, amount, currency, authorization_code (для их изменения - удалить и создать заново).

    Внимание: description и counterparty_name ВХОДЯТ в transaction_hash v1.
    Изменение этих полей НЕ пересчитывает хэш - он остаётся «снимком на момент импорта».
    Это значит, что повторный импорт того же PDF всё равно
    будет пойман как duplicate_statement (по file_hash), а транзакция с
    оригинальным описанием из другого PDF - как skipped_cross_batch (по transaction_hash). См. README.
    """
    tx = _get_transaction_or_raise(session, transaction_id)

    if not isinstance(category_id, _UnsetType):
        _validate_category_id(session, category_id)
        tx.category_id = category_id

    if not isinstance(description, _UnsetType):
        tx.description = (description or "").strip() or None

    if not isinstance(counterparty_name, _UnsetType):
        tx.counterparty_name = counterparty_name or None

    if not isinstance(is_transfer, _UnsetType):
        tx.is_transfer = bool(is_transfer)

    session.flush()
    return tx


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_transaction(session: Session, transaction_id: int) -> None:
    """Hard delete. ValueError, если не найдена.

    Statement не удаляется - file_hash остаётся зафиксированным
    (защита от повторного импорта).
    """
    tx = _get_transaction_or_raise(session, transaction_id)
    session.delete(tx)
    session.flush()


# ---------------------------------------------------------------------------
# Manual add
# ---------------------------------------------------------------------------

def add_manual_transaction(
    session: Session,
    *,
    account_id: int,
    date: date,
    amount: int,
    time: time | None = None,
    description: str = "",
    currency: str | None = None,
    counterparty_name: str | None = None,
    category_id: int | None = None,
    is_transfer: bool = False,
    account_key: str | None = None,
) -> Transaction:
    """Ручное добавление транзакции. source='manual', statement_id=None.

    Хэш считается тем же правилом v1, что и для PDF -> корректно отклонит
    дубликат уже существующей (account_id, transaction_hash).

    Args:
        account_key: необязательный бизнес-ключ счёта для хэша. По умолчанию str(account_id).

    Raises:
        ValueError: account не найден; валюта не определена / не совпадает
                    с валютой счёта / не в TRANSACTION_CURRENCIES;
                    category_id не существует.
        DuplicateTransactionError: (account_id, transaction_hash) уже есть.
    """
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"account with id={account_id} not found")

    _validate_category_id(session, category_id)

    final_account_key = account_key if account_key is not None else str(account_id)

    if currency is not None:
        original = currency
        currency = currency.strip().upper()
        if currency not in TRANSACTION_CURRENCIES:
            raise ValueError(f"unsupported currency: {original!r}")

    prepared = prepare_transaction(
        account_id=account_id,
        account_currency=account.currency,
        account_key=final_account_key,
        date=date,
        time=time,
        amount=amount,
        currency=currency,
        description=description,
        counterparty_name=counterparty_name,
        auth=None,
        category="",
    )
    if not prepared.is_valid:
        raise ValueError(
            "invalid manual transaction: "
            + ", ".join(prepared.validation_errors)
        )

    existing_id = session.execute(
        select(Transaction.transaction_id).where(
            Transaction.account_id == account_id,
            Transaction.transaction_hash == prepared.transaction_hash,
        )
    ).scalar_one_or_none()
    if existing_id is not None:
        raise DuplicateTransactionError(
            f"transaction with the same hash already exists "
            f"(id={existing_id})",
            existing_transaction_id=existing_id,
            transaction_hash=prepared.transaction_hash,
        )

    tx = Transaction(
        account_id=account_id,
        statement_id=None,
        date=prepared.date,
        time=prepared.time,
        amount=prepared.amount,
        currency=prepared.currency,
        description=(prepared.description or "").strip() or None,
        counterparty_name=prepared.counterparty_name,
        category_id=category_id,
        authorization_code=prepared.authorization_code,
        raw_category=prepared.raw_category,
        is_transfer=is_transfer,
        transaction_hash=prepared.transaction_hash,
        hash_version=prepared.hash_version,
        source="manual",
    )
    session.add(tx)
    session.flush()
    return tx


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_transaction(
    session: Session, transaction_id: int
) -> Transaction | None:
    """None если не найдена."""
    return session.get(Transaction, transaction_id)


def list_transactions(
    session: Session,
    *,
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    is_transfer: bool | None = None,
    description_query: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Transaction]:
    """Сортировка: date DESC, time DESC, transaction_id DESC.

    date_from/date_to - включительно (date_from <= date <= date_to).
    description_query - подстрока для поиска по description или
        counterparty_name (case-insensitive; для кириллицы требуется custom lower() на SQLite).
    limit=None -> без ограничения. limit <= 0 -> ValueError.
    offset < 0 -> ValueError.
    """
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if is_transfer is not None:
        stmt = stmt.where(Transaction.is_transfer == is_transfer)

    if description_query and description_query.strip():
        pattern = f"%{description_query.strip()}%"
        stmt = stmt.where(
            Transaction.description.ilike(pattern)
            | Transaction.counterparty_name.ilike(pattern)
        )

    stmt = stmt.order_by(
        Transaction.date.desc(),
        Transaction.time.desc().nullslast(),
        Transaction.transaction_id.desc(),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)

    return list(session.execute(stmt).scalars().all())


def count_transactions(
    session: Session,
    *,
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    is_transfer: bool | None = None,
    description_query: str | None = None,
) -> int:
    """Число транзакций с фильтрами (без пагинации).

    description_query - те же правила, что в list_transactions.
    """
    stmt = select(func.count(Transaction.transaction_id))
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if is_transfer is not None:
        stmt = stmt.where(Transaction.is_transfer == is_transfer)

    if description_query and description_query.strip():
        pattern = f"%{description_query.strip()}%"
        stmt = stmt.where(
            Transaction.description.ilike(pattern)
            | Transaction.counterparty_name.ilike(pattern)
        )

    return session.execute(stmt).scalar_one()


# =========================================================================
# Агрегации для UI-4: счётчики по категориям и группировка по raw_category
# =========================================================================

@dataclass(frozen=True, slots=True)
class RawCategoryGroup:
    """Сводка по одной группе raw_category (для bulk-assign)."""

    raw_category: str | None
    total_count: int
    uncategorized_count: int
    total_amount: int  # сумма в копейках


def count_transactions_by_category(
    session: Session,
    *,
    account_id: int | None = None,
) -> dict[int, int]:
    """{category_id: count} - одним SELECT GROUP BY, без N+1.

    Транзакции с `category_id IS NULL` в результат не входят.
    """
    stmt = (
        select(Transaction.category_id, func.count(Transaction.transaction_id))
        .where(Transaction.category_id.is_not(None))
        .group_by(Transaction.category_id)
    )
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    return {row[0]: row[1] for row in session.execute(stmt)}


def list_raw_category_groups(
    session: Session,
    *,
    account_id: int | None = None,
) -> list[RawCategoryGroup]:
    """Сгруппировать транзакции по raw_category.

    Возвращает все группы, включая:
    - raw_category=None (транзакции без «сырой» категории);
    - группы с uncategorized_count=0 (уже все назначены).

    Сортировка: по raw_category (None - в конце, из-за NULLS LAST в SQLite
    через `order_by(Transaction.raw_category.is_(None), Transaction.raw_category)`).
    """
    stmt = (
        select(
            Transaction.raw_category,
            func.count(Transaction.transaction_id).label("total"),
            func.count(case((Transaction.category_id.is_(None), 1))).label("uncat"),
            func.coalesce(func.sum(Transaction.amount), 0).label("amount"),
        )
        .group_by(Transaction.raw_category)
        .order_by(
            Transaction.raw_category.is_(None),
            Transaction.raw_category,
        )
    )
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)

    return [
        RawCategoryGroup(
            raw_category=row.raw_category,
            total_count=row.total,
            uncategorized_count=row.uncat,
            total_amount=row.amount,
        )
        for row in session.execute(stmt)
    ]


def assign_category_to_raw_group(
    session: Session,
    *,
    raw_category: str | None,
    category_id: int,
    account_id: int | None = None,
) -> int:
    """Назначить category_id всем транзакциям с raw_category и category_id IS NULL.

    **Не перезаписывает уже назначенные категории.** Возвращает число
    обновлённых строк. Не коммитит - это забота вызывающего (unit-of-work).
    """

    _validate_category_id(session, category_id)

    conditions = [Transaction.category_id.is_(None)]
    if raw_category is None:
        conditions.append(Transaction.raw_category.is_(None))
    else:
        conditions.append(Transaction.raw_category == raw_category)
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)

    stmt = (
        update(Transaction)
        .where(*conditions)
        .values(category_id=category_id)
    )
    result = session.execute(stmt)
    return result.rowcount or 0