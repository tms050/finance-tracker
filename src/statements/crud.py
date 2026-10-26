"""Чтение и удаление Statement.

Удаление транзакций при удалении Statement - опционально (cascade_transactions), см. delete_statement.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.db import Statement, Transaction


@dataclass(frozen=True, slots=True)
class DeleteStatementResult:
    statement_id: int
    deleted_transactions: int    # удалено при cascade_transactions=True
    unlinked_transactions: int   # statement_id -> NULL при cascade_transactions=False


def get_statement(session: Session, statement_id: int) -> Statement | None:
    """None если не найден."""
    return session.get(Statement, statement_id)


def get_statement_by_file_hash(
    session: Session, file_hash: str
) -> Statement | None:
    """None если не найден."""
    return session.execute(
        select(Statement).where(Statement.file_hash == file_hash)
    ).scalar_one_or_none()


def list_statements(
    session: Session,
    *,
    account_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Statement]:
    """Сортировка: period_start DESC, statement_id DESC.

    limit=None - без ограничения; limit <= 0 -> ValueError; offset < 0 -> ValueError.
    """
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    stmt = select(Statement)
    if account_id is not None:
        stmt = stmt.where(Statement.account_id == account_id)
    stmt = stmt.order_by(
        Statement.period_start.desc().nullslast(),
        Statement.statement_id.desc(),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)
    return list(session.execute(stmt).scalars().all())


def delete_statement(
    session: Session,
    statement_id: int,
    *,
    cascade_transactions: bool = True,
) -> DeleteStatementResult:
    """Удалить Statement.

    cascade_transactions=True (default):
        Удаляются Statement и все транзакции с этим statement_id.
        Сценарий: «переимпортировать исправленный PDF».

    cascade_transactions=False:
        Удаляется только Statement. FK ON DELETE SET NULL обнуляет 
        statement_id у транзакций на уровне БД - независимо от того, загружена ли stmt.transactions.
        ВНИМАНИЕ: transaction_hash сохраняется - при повторном импорте
        того же PDF они уйдут в skipped_cross_batch.

    Raises:
        ValueError: statement не найден.
    """
    stmt = session.get(Statement, statement_id)
    if stmt is None:
        raise ValueError(f"statement with id={statement_id} not found")

    tx_count = session.execute(
        select(func.count(Transaction.transaction_id)).where(
            Transaction.statement_id == statement_id
        )
    ).scalar_one()

    if cascade_transactions:
        if tx_count:
            result = session.execute(
                delete(Transaction).where(
                    Transaction.statement_id == statement_id
                ),
                execution_options={"synchronize_session": False},
            )
            deleted = result.rowcount or 0
        else:
            deleted = 0
        unlinked = 0
    else:
        deleted, unlinked = 0, tx_count

    session.delete(stmt)   # DELETE FROM statements WHERE id = ?
    session.flush()        # DB применит SET NULL (или ничего, если cascade=True)
    return DeleteStatementResult(
        statement_id=statement_id,
        deleted_transactions=deleted,
        unlinked_transactions=unlinked,
    )