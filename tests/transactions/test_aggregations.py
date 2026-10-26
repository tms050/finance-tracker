"""Тесты агрегаций для UI-4."""
from __future__ import annotations

import itertools
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from src.accounts import create_account
from src.categories import create_category
from src.db import init_db
from src.transactions import (
    RawCategoryGroup,
    assign_category_to_raw_group,
    count_transactions_by_category,
    list_raw_category_groups,
)


# ---------------------------------------------------------------------------
# Фикстуры (локальные, как в test_crud.py — conftest из tests/db/ сюда
# не достаёт по scope)
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture
def account(session):
    return create_account(
        session, bank_name="Sber", account_name="Test",
        account_number_masked="**** 1234", currency="RUB",
    )


@pytest.fixture
def account2(session):
    return create_account(
        session, bank_name="Sber", account_name="Test2",
        account_number_masked="**** 5678", currency="RUB",
    )


# ---------------------------------------------------------------------------
# Хелпер: транзакция напрямую через ORM (add_manual_transaction не принимает
# raw_category). transaction_hash уникален через counter.
# ---------------------------------------------------------------------------

_hash_counter = itertools.count(1)


def _make_tx(session, account_id, *, amount=-1000, raw_category=None,
             category_id=None, description="tx"):
    from src.db import Transaction
    tx = Transaction(
        account_id=account_id,
        date=date(2024, 1, 15),
        amount=amount,
        currency="RUB",
        description=description,
        raw_category=raw_category,
        category_id=category_id,
        is_transfer=False,
        transaction_hash=f"test_hash_{next(_hash_counter)}",
        hash_version=1,
        source="manual",
    )
    session.add(tx)
    session.flush()
    return tx


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

def test_smoke_create_account(session):
    """Проверка окружения: фикстура session + create_account работают."""
    acc = create_account(
        session, bank_name="SmokeBank", account_name="Smoke",
        account_number_masked="**** 0001", currency="RUB",
    )
    assert acc.account_id is not None


# ---------------------------------------------------------------------------
# count_transactions_by_category
# ---------------------------------------------------------------------------

def test_count_empty(session):
    assert count_transactions_by_category(session) == {}


def test_count_grouped(session, account):
    cat1 = create_category(session, "Food", "expense")
    cat2 = create_category(session, "Transport", "expense")
    _make_tx(session, account.account_id, category_id=cat1.category_id)
    _make_tx(session, account.account_id, category_id=cat1.category_id)
    _make_tx(session, account.account_id, category_id=cat2.category_id)
    _make_tx(session, account.account_id, category_id=None)  # не считается

    result = count_transactions_by_category(session)
    assert result == {cat1.category_id: 2, cat2.category_id: 1}


def test_count_filtered_by_account(session, account, account2):
    cat = create_category(session, "Food", "expense")
    _make_tx(session, account.account_id, category_id=cat.category_id)
    _make_tx(session, account2.account_id, category_id=cat.category_id)
    _make_tx(session, account2.account_id, category_id=cat.category_id)

    assert count_transactions_by_category(
        session, account_id=account.account_id
    ) == {cat.category_id: 1}
    assert count_transactions_by_category(
        session, account_id=account2.account_id
    ) == {cat.category_id: 2}


# ---------------------------------------------------------------------------
# list_raw_category_groups
# ---------------------------------------------------------------------------

def test_raw_groups_empty(session):
    assert list_raw_category_groups(session) == []


def test_raw_groups_basic(session, account):
    cat = create_category(session, "Food", "expense")
    _make_tx(session, account.account_id, raw_category="Супермаркеты",
             category_id=None, amount=-1000)
    _make_tx(session, account.account_id, raw_category="Супермаркеты",
             category_id=cat.category_id, amount=-2000)
    _make_tx(session, account.account_id, raw_category="Кафе",
             category_id=None, amount=-500)

    groups = list_raw_category_groups(session, account_id=account.account_id)
    by_rc = {g.raw_category: g for g in groups}

    assert by_rc["Супермаркеты"].total_count == 2
    assert by_rc["Супермаркеты"].uncategorized_count == 1
    assert by_rc["Супермаркеты"].total_amount == -3000

    assert by_rc["Кафе"].total_count == 1
    assert by_rc["Кафе"].uncategorized_count == 1
    assert by_rc["Кафе"].total_amount == -500


def test_raw_groups_with_null_category(session, account):
    _make_tx(session, account.account_id, raw_category=None, category_id=None)
    groups = list_raw_category_groups(session, account_id=account.account_id)
    assert len(groups) == 1
    assert groups[0].raw_category is None
    assert groups[0].uncategorized_count == 1


def test_raw_groups_filtered_by_account(session, account, account2):
    _make_tx(session, account.account_id, raw_category="A", amount=-100)
    _make_tx(session, account2.account_id, raw_category="A", amount=-200)
    _make_tx(session, account2.account_id, raw_category="A", amount=-300)

    groups = list_raw_category_groups(session, account_id=account2.account_id)
    assert len(groups) == 1
    assert groups[0].total_count == 2
    assert groups[0].total_amount == -500


# ---------------------------------------------------------------------------
# assign_category_to_raw_group
# ---------------------------------------------------------------------------

def test_assign_bulk(session, account):
    cat = create_category(session, "Food", "expense")
    tx1 = _make_tx(session, account.account_id, raw_category="Супермаркеты",
                   category_id=None)
    tx2 = _make_tx(session, account.account_id, raw_category="Супермаркеты",
                   category_id=None)
    tx3 = _make_tx(session, account.account_id, raw_category="Супермаркеты",
                   category_id=cat.category_id)

    updated = assign_category_to_raw_group(
        session, raw_category="Супермаркеты",
        category_id=cat.category_id, account_id=account.account_id,
    )
    assert updated == 2

    session.refresh(tx1); session.refresh(tx2); session.refresh(tx3)
    assert tx1.category_id == cat.category_id
    assert tx2.category_id == cat.category_id
    assert tx3.category_id == cat.category_id  # не перезаписан


def test_assign_does_not_touch_other_raw(session, account):
    cat = create_category(session, "Food", "expense")
    tx_a = _make_tx(session, account.account_id, raw_category="A",
                    category_id=None)
    tx_b = _make_tx(session, account.account_id, raw_category="B",
                    category_id=None)

    assign_category_to_raw_group(
        session, raw_category="A", category_id=cat.category_id,
        account_id=account.account_id,
    )
    session.refresh(tx_a); session.refresh(tx_b)
    assert tx_a.category_id == cat.category_id
    assert tx_b.category_id is None


def test_assign_returns_zero_when_all_assigned(session, account):
    cat = create_category(session, "Food", "expense")
    _make_tx(session, account.account_id, raw_category="A",
             category_id=cat.category_id)
    updated = assign_category_to_raw_group(
        session, raw_category="A", category_id=cat.category_id,
        account_id=account.account_id,
    )
    assert updated == 0


def test_assign_respects_account_filter(session, account, account2):
    cat = create_category(session, "Food", "expense")
    tx_a = _make_tx(session, account.account_id, raw_category="X",
                    category_id=None)
    tx_b = _make_tx(session, account2.account_id, raw_category="X",
                    category_id=None)

    assign_category_to_raw_group(
        session, raw_category="X", category_id=cat.category_id,
        account_id=account.account_id,
    )
    session.refresh(tx_a); session.refresh(tx_b)
    assert tx_a.category_id == cat.category_id
    assert tx_b.category_id is None