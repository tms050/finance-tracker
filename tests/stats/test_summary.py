"""Тесты src.stats.get_summary."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db import init_db
from src.db.models import Account, Category, Transaction
from src.stats.summary import Summary, get_summary


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        s.add_all([
            Account(
                account_id=1, bank_name="Sber", account_name="A",
                account_number_masked="**** 0001", currency="RUB",
            ),
            Account(
                account_id=2, bank_name="Sber", account_name="B",
                account_number_masked="**** 0002", currency="RUB",
            ),
        ])
        s.commit()
        yield s
        s.rollback()


_counter = [0]

def add_tx(
    session,
    *,
    amount: int,
    account_id: int = 1,
    date_: date = date(2024, 1, 15),
    is_transfer: bool = False,
    category_id: int | None = None,
) -> Transaction:
    _counter[0] += 1
    tx = Transaction(
        account_id=account_id, date=date_, amount=amount,
        currency="RUB", description="x",
        transaction_hash=f"h-{_counter[0]}",
        hash_version=1, source="pdf",
        is_transfer=is_transfer, category_id=category_id,
    )
    session.add(tx)
    session.flush()
    return tx


# ---------------------------------------------------------------------------
# Базовые сценарии
# ---------------------------------------------------------------------------

def test_empty_returns_zeros(session):
    assert get_summary(session) == Summary(0, 0, 0, 0, 0)


def test_income_only(session):
    add_tx(session, amount=10000)
    add_tx(session, amount=5000)
    s = get_summary(session)
    assert s.income == 15000
    assert s.expense == 0
    assert s.net == 15000
    assert s.count == 2
    assert s.transfer_count == 0


def test_expense_only(session):
    add_tx(session, amount=-10000)
    add_tx(session, amount=-5000)
    s = get_summary(session)
    assert s.income == 0
    assert s.expense == 15000         # положительная величина
    assert s.net == -15000
    assert s.count == 2


def test_mixed(session):
    add_tx(session, amount=10000)
    add_tx(session, amount=-3000)
    add_tx(session, amount=-2000)
    s = get_summary(session)
    assert s.income == 10000
    assert s.expense == 5000
    assert s.net == 5000
    assert s.count == 3


# ---------------------------------------------------------------------------
# Переводы
# ---------------------------------------------------------------------------

def test_transfers_excluded(session):
    add_tx(session, amount=10000)
    add_tx(session, amount=-10000, is_transfer=True)
    add_tx(session, amount=5000, is_transfer=True)
    s = get_summary(session)
    assert s.income == 10000
    assert s.expense == 0
    assert s.net == 10000
    assert s.count == 1
    assert s.transfer_count == 2


# ---------------------------------------------------------------------------
# Edge: amount=0
# ---------------------------------------------------------------------------

def test_zero_amount_counts_in_count_only(session):
    add_tx(session, amount=0)
    add_tx(session, amount=1000)
    s = get_summary(session)
    assert s.count == 2               # нулевая тоже посчитана
    assert s.income == 1000
    assert s.expense == 0


# ---------------------------------------------------------------------------
# Фильтры
# ---------------------------------------------------------------------------

def test_filter_by_account(session):
    add_tx(session, amount=1000, account_id=1)
    add_tx(session, amount=2000, account_id=2)
    s1 = get_summary(session, account_id=1)
    s2 = get_summary(session, account_id=2)
    assert s1.income == 1000
    assert s2.income == 2000


def test_filter_by_dates(session):
    add_tx(session, amount=1000, date_=date(2024, 1, 5))
    add_tx(session, amount=2000, date_=date(2024, 1, 15))
    add_tx(session, amount=3000, date_=date(2024, 1, 25))

    assert get_summary(session, date_from=date(2024, 1, 10)).income == 5000
    assert get_summary(session, date_to=date(2024, 1, 15)).income == 3000
    assert get_summary(
        session, date_from=date(2024, 1, 10), date_to=date(2024, 1, 20),
    ).income == 2000


def test_filter_by_category(session):
    cat = Category(name="Food", type="expense")
    session.add(cat)
    session.flush()

    add_tx(session, amount=-1000, category_id=cat.category_id)
    add_tx(session, amount=-2000)

    s = get_summary(session, category_id=cat.category_id)
    assert s.expense == 1000
    assert s.count == 1


def test_all_filters_combined(session):
    cat = Category(name="Food", type="expense")
    session.add(cat)
    session.flush()
    add_tx(session, amount=-1000, account_id=1,
           date_=date(2024, 1, 10), category_id=cat.category_id)
    add_tx(session, amount=-5000, account_id=1,
           date_=date(2024, 3, 10), category_id=cat.category_id)
    add_tx(session, amount=-9999, account_id=2,
           date_=date(2024, 1, 10), category_id=cat.category_id)

    s = get_summary(
        session, account_id=1,
        date_from=date(2024, 1, 1), date_to=date(2024, 1, 31),
        category_id=cat.category_id,
    )
    assert s.expense == 1000
    assert s.count == 1

def test_inverted_date_range_raises(session):
    with pytest.raises(ValueError, match="date_from"):
        get_summary(
            session,
            date_from=date(2024, 12, 31),
            date_to=date(2024, 1, 1),
        )


def test_equal_dates_allowed(session):
    """date_from == date_to — не ошибка, это одна конкретная дата."""
    add_tx(session, amount=1000, date_=date(2024, 1, 15))
    s = get_summary(
        session,
        date_from=date(2024, 1, 15),
        date_to=date(2024, 1, 15),
    )
    assert s.income == 1000
    assert s.count == 1


def test_total_count_matches_count_transactions(session):
    from src.transactions import count_transactions
    add_tx(session, amount=1000)
    add_tx(session, amount=-500)
    add_tx(session, amount=-10000, is_transfer=True)
    add_tx(session, amount=5000, is_transfer=True)

    s = get_summary(session)
    assert s.total_count == s.count + s.transfer_count
    assert s.total_count == count_transactions(session)


def test_has_data_empty(session):
    assert get_summary(session).has_data is False


def test_has_data_only_transfers(session):
    add_tx(session, amount=-10000, is_transfer=True)
    s = get_summary(session)
    assert s.count == 0
    assert s.transfer_count == 1
    assert s.has_data is True


def test_category_filter_includes_transfer_count(session):
    """Зафиксировать известное поведение из docstring (п.5 ревью)."""
    cat = Category(name="Transfer-Cat", type="transfer")
    session.add(cat)
    session.flush()

    add_tx(session, amount=-10000, is_transfer=True, category_id=cat.category_id)
    add_tx(session, amount=-2000)  # non-transfer, без категории

    s = get_summary(session, category_id=cat.category_id)
    assert s.income == 0
    assert s.expense == 0
    assert s.count == 0
    assert s.transfer_count == 1   # ← попал под фильтр по категории