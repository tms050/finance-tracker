"""B2a: импорт PreparedStatement в БД.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import Statement as DBStatement
from src.db import Transaction as DBTransaction
from src.importing.prepare import PreparedStatement


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class IntraBatchSkip:
    """Транзакция, пропущенная из-за коллизии внутри батча."""

    original_index: int
    transaction_hash: str
    reason: Literal["intra_batch_collision"] = "intra_batch_collision"


@dataclass(frozen=True, slots=True)
class CrossBatchSkip:
    """Транзакция, пропущенная из-за коллизии с уже существующей в БД."""

    original_index: int
    transaction_hash: str
    existing_transaction_id: int
    reason: Literal["cross_batch_conflict"] = "cross_batch_conflict"


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Результат import_prepared_statement."""

    status: Literal["ok", "duplicate_statement", "no_valid_transactions"]
    statement_id: int | None
    inserted_transactions: tuple[int, ...] = ()
    skipped_intra_batch: tuple[IntraBatchSkip, ...] = ()
    skipped_cross_batch: tuple[CrossBatchSkip, ...] = ()
    created_categories: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Хелпер с чанками
# ---------------------------------------------------------------------------

def _get_existing_hashes(
    session: Session,
    account_id: int,
    hashes: Iterable[str],
    chunk_size: int = 500,
) -> dict[str, int]:
    """SELECT transaction_hash, transaction_id для набора hashes (чанками)."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    result: dict[str, int] = {}
    hashes_list = list(hashes)
    for i in range(0, len(hashes_list), chunk_size):
        chunk = hashes_list[i : i + chunk_size]
        stmt = (
            select(DBTransaction.transaction_hash, DBTransaction.transaction_id)
            .where(
                DBTransaction.account_id == account_id,
                DBTransaction.transaction_hash.in_(chunk),
            )
        )
        for row in session.execute(stmt):
            result[row.transaction_hash] = row.transaction_id
    return result

def _find_existing_statement_id(
    session: Session, file_hash: str
) -> int | None:
    """Вернуть statement_id по file_hash, или None.

    Internal: используется также в categories.py (B2b) для early-dedup.
    """
    return session.execute(
        select(DBStatement.statement_id).where(
            DBStatement.file_hash == file_hash
        )
    ).scalar_one_or_none()

# ---------------------------------------------------------------------------
# import_prepared_statement
# ---------------------------------------------------------------------------

def import_prepared_statement(
    session: Session,
    prepared: PreparedStatement,
    *,
    chunk_size: int = 500,
) -> ImportResult:
    """Импортирует PreparedStatement в БД.

    Args:
        session: SQLAlchemy-сессия (unit-of-work).
        prepared: результат prepare_statement из B1.
        chunk_size: размер чанка для IN-запроса (нюанс 1).

    Raises:
        ValueError: если prepared.account_id is None.
                    В B2a find_or_create_account не поддерживается (B2d).

    Заметка: счёт НЕЛЬЗЯ переопределить здесь - хэши привязаны к account_id
    (account_key = str(account_id) по умолчанию). Если нужен другой счёт,
    вызовите prepare_statement заново с правильным account_id.
    """
    if prepared.account_id is None:
        raise ValueError(
            "prepared.account_id is None; B2a requires an explicit account_id "
            "(find_or_create_account - задача B2d)"
        )
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    account_id = prepared.account_id

    existing_statement_id = _find_existing_statement_id(
        session, prepared.file_hash
    )
    if existing_statement_id is not None:
        return ImportResult(
            status="duplicate_statement",
            statement_id=existing_statement_id,
        )

    if not prepared.transactions_to_insert:
        return ImportResult(
            status="no_valid_transactions",
            statement_id=None,
        )

    statement = DBStatement(
        account_id=account_id,
        file_name=prepared.file_name,
        file_hash=prepared.file_hash,
        period_start=prepared.period_start,
        period_end=prepared.period_end,
    )
    session.add(statement)
    session.flush()

    skip_intra: dict[int, IntraBatchSkip] = {}
    for group in prepared.intra_batch_collisions:
        for p in group.transactions[1:]:
            skip_intra[p.original_index] = IntraBatchSkip(
                original_index=p.original_index,
                transaction_hash=group.transaction_hash,
            )
    to_insert = [
        p for p in prepared.transactions_to_insert
        if p.original_index not in skip_intra
    ]

    candidate_hashes = {p.transaction_hash for p in to_insert}
    existing = _get_existing_hashes(session, account_id, candidate_hashes, chunk_size)
    skip_cross: dict[int, CrossBatchSkip] = {}
    final_to_insert = []
    for p in to_insert:
        existing_id = existing.get(p.transaction_hash)
        if existing_id is not None:
            skip_cross[p.original_index] = CrossBatchSkip(
                original_index=p.original_index,
                transaction_hash=p.transaction_hash,
                existing_transaction_id=existing_id,
            )
        else:
            final_to_insert.append(p)

    inserted_txs: list[DBTransaction] = []
    for p in final_to_insert:
        tx = DBTransaction(
            account_id=account_id,
            statement_id=statement.statement_id,
            date=p.date,
            time=p.time,
            amount=p.amount,
            currency=p.currency,
            description=p.description,
            counterparty_name=p.counterparty_name,
            category_id=p.category_id,           # в B2a всегда None
            authorization_code=p.authorization_code,
            raw_category=p.raw_category,
            is_transfer=p.is_transfer,
            transaction_hash=p.transaction_hash,
            hash_version=p.hash_version,
            source=p.source,
        )
        session.add(tx)
        inserted_txs.append(tx)
    session.flush()

    inserted_ids = tuple(tx.transaction_id for tx in inserted_txs)

    warnings: list[str] = []
    total_skipped = len(skip_intra) + len(skip_cross)
    if total_skipped > 0:
        if not inserted_ids:
            warnings.append(
                f"Все {total_skipped} транзакций пропущены как дубликаты: "
                f"внутри батча {len(skip_intra)}, с существующими "
                f"{len(skip_cross)}. Statement создан."
            )
        else:
            warnings.append(
                f"Пропущено {total_skipped} транзакций: "
                f"внутри батча {len(skip_intra)}, с существующими "
                f"{len(skip_cross)}."
            )

    return ImportResult(
        status="ok",
        statement_id=statement.statement_id,
        inserted_transactions=inserted_ids,
        skipped_intra_batch=tuple(skip_intra.values()),
        skipped_cross_batch=tuple(skip_cross.values()),
        created_categories=(),     # B2b
        warnings=tuple(warnings),
    )