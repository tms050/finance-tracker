"""UC-03: доходы, расходы, количество, исключая переводы."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.db import Transaction


@dataclass(frozen=True, slots=True)
class Summary:
    income: int             # >= 0, сумма положительных non-transfer amount
    expense: int            # >= 0, |сумма отрицательных non-transfer amount|
    net: int                # income - expense
    count: int              # число non-transfer транзакций (включая amount=0)
    transfer_count: int     # число is_transfer=True

    @property
    def total_count(self) -> int:
        """count + transfer_count.

        Согласовано с count_transactions(session) без фильтров.
        Используйте, когда нужно «сколько всего операций» (с переводами),
        а не «сколько non-transfer» (count).
        """
        return self.count + self.transfer_count

    @property
    def has_data(self) -> bool:
        """True, если есть хоть одна транзакция (обычная или перевод).

        Удобно для empty-state в UI: `if not summary.has_data: ...`.
        """
        return (self.count + self.transfer_count) > 0

    @property
    def total_count(self) -> int:
        return self.count + self.transfer_count

    @property
    def has_data(self) -> bool:
        return (self.count + self.transfer_count) > 0


def get_summary(
    session: Session,
    *,
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
) -> Summary:
    """Агрегаты по фильтрам. Переводы исключены из income/expense/net/count,
    учтены отдельно в transfer_count. Пустые данные -> Summary(0,0,0,0,0).

    Args:
        account_id: фильтр по счёту.
        date_from: нижняя граница даты включительно (>=).
        date_to: верхняя граница даты включительно (<=).
        category_id: фильтр по категории. Применяется ко ВСЕМ агрегатам,
            включая transfer_count. Обычно переводы не категоризируются -
            но если у перевода выставлен category_id, он попадёт в
            transfer_count при фильтре по этой категории. См. UI-3
            (там фильтр по категории сознательно не выведен).

    Raises:
        ValueError: date_from > date_to (иначе молча вернули бы нули,
            что в UI выглядит как «пусто, странно»).
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError(
            f"date_from ({date_from}) must be <= date_to ({date_to})"
        )

    # is_transfer - INTEGER NOT NULL (0/1), поэтому == 0 / == 1, а не .is_().
    stmt = select(
        func.coalesce(
            func.sum(case(
                (
                    (Transaction.is_transfer == 0)
                    & (Transaction.amount > 0),
                    Transaction.amount,
                ),
                else_=0,
            )),
            0,
        ).label("income"),
        func.coalesce(
            func.sum(case(
                (
                    (Transaction.is_transfer == 0)
                    & (Transaction.amount < 0),
                    -Transaction.amount,
                ),
                else_=0,
            )),
            0,
        ).label("expense"),
        func.coalesce(
            func.sum(case(
                (Transaction.is_transfer == 0, 1),
                else_=0,
            )),
            0,
        ).label("count"),
        func.coalesce(
            func.sum(case(
                (Transaction.is_transfer == 1, 1),
                else_=0,
            )),
            0,
        ).label("transfer_count"),
    )
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)

    row = session.execute(stmt).one()
    # coalesce(..., 0) уже гарантирует не-NULL.
    income = int(row.income)
    expense = int(row.expense)
    return Summary(
        income=income,
        expense=expense,
        net=income - expense,
        count=int(row.count),
        transfer_count=int(row.transfer_count),
    )