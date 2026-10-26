"""Тесты src.categories.crud."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src._internal.sentinel import UNSET
from src.categories.crud import (
    create_category,
    delete_category,
    get_category,
    list_categories,
    rename_category,
)
from src.db import init_db
from src.db.models import Account, Category, Transaction


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        s.add(Account(
            account_id=1, bank_name="Sber", account_name="A",
            account_number_masked="**** 0001", currency="RUB",
        ))
        s.commit()
        yield s
        s.rollback()


# ---------------------------------------------------------------------------
# get_category
# ---------------------------------------------------------------------------

def test_get_category_found(session):
    c = create_category(session, "Food", "expense")
    assert get_category(session, c.category_id).category_id == c.category_id


def test_get_category_not_found(session):
    assert get_category(session, 999) is None


# ---------------------------------------------------------------------------
# create_category
# ---------------------------------------------------------------------------

def test_create_ok(session):
    c = create_category(session, "Food", "expense")
    assert c.category_id is not None
    assert c.name == "Food"
    assert c.type == "expense"


def test_create_strips_name(session):
    c = create_category(session, "  Food  ", "expense")
    assert c.name == "Food"


def test_create_empty_name(session):
    with pytest.raises(ValueError):
        create_category(session, "", "expense")
    with pytest.raises(ValueError):
        create_category(session, "   ", "expense")


def test_create_duplicate(session):
    create_category(session, "Food", "expense")
    with pytest.raises(ValueError):
        create_category(session, "Food", "expense")


def test_create_same_name_different_parent(session):
    parent = create_category(session, "Food", "expense")
    a = create_category(session, "Coffee", "expense", parent.category_id)
    b = create_category(session, "Coffee", "expense", None)
    assert a.category_id != b.category_id


def test_create_case_sensitive(session):
    a = create_category(session, "Food", "expense")
    b = create_category(session, "food", "expense")
    assert a.category_id != b.category_id


# ---------------------------------------------------------------------------
# rename_category
# ---------------------------------------------------------------------------

def test_rename_ok(session):
    c = create_category(session, "Old", "expense")
    renamed = rename_category(session, c.category_id, "New")
    assert renamed.name == "New"


def test_rename_conflict(session):
    create_category(session, "A", "expense")
    b = create_category(session, "B", "expense")
    with pytest.raises(ValueError):
        rename_category(session, b.category_id, "A")


def test_rename_not_found(session):
    with pytest.raises(ValueError):
        rename_category(session, 999, "X")


def test_rename_empty(session):
    c = create_category(session, "A", "expense")
    with pytest.raises(ValueError):
        rename_category(session, c.category_id, "   ")


def test_rename_same_name_no_conflict(session):
    c = create_category(session, "A", "expense")
    renamed = rename_category(session, c.category_id, "A")
    assert renamed.name == "A"


# ---------------------------------------------------------------------------
# delete_category
# ---------------------------------------------------------------------------

def test_delete_unlinks_transactions(session):
    c = create_category(session, "Food", "expense")
    tx = Transaction(
        account_id=1, date=date(2024, 1, 15), amount=-100, currency="RUB",
        description="x", transaction_hash="h1", hash_version=1,
        source="pdf", category_id=c.category_id,
    )
    session.add(tx)
    session.flush()
    tx_id, cid = tx.transaction_id, c.category_id

    delete_category(session, cid)

    session.expire_all()
    assert get_category(session, cid) is None
    tx2 = session.get(Transaction, tx_id)
    assert tx2 is not None
    assert tx2.category_id is None


def test_delete_not_found(session):
    with pytest.raises(ValueError):
        delete_category(session, 999)


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert list_categories(session) == []


def test_list_all(session):
    create_category(session, "A", "expense")
    create_category(session, "B", "income")
    assert len(list_categories(session)) == 2


def test_list_roots_only(session):
    parent = create_category(session, "Food", "expense")
    create_category(session, "Coffee", "expense", parent.category_id)
    roots = list_categories(session, parent_id=None)
    assert [c.category_id for c in roots] == [parent.category_id]


def test_list_children_of_parent(session):
    p1 = create_category(session, "Food", "expense")
    p2 = create_category(session, "Transport", "expense")
    c1 = create_category(session, "Coffee", "expense", p1.category_id)
    create_category(session, "Metro", "expense", p2.category_id)
    children = list_categories(session, parent_id=p1.category_id)
    assert [c.category_id for c in children] == [c1.category_id]


def test_list_unset_returns_all(session):
    parent = create_category(session, "Food", "expense")
    create_category(session, "Coffee", "expense", parent.category_id)
    assert len(list_categories(session, parent_id=UNSET)) == 2


def test_list_filter_by_type(session):
    create_category(session, "Salary", "income")
    create_category(session, "Food", "expense")
    create_category(session, "Transfer", "transfer")
    assert len(list_categories(session, type="income")) == 1
    assert len(list_categories(session, type="expense")) == 1


def test_list_sorting_by_name(session):
    create_category(session, "C", "expense")
    create_category(session, "A", "expense")
    create_category(session, "B", "expense")
    names = [c.name for c in list_categories(session)]
    assert names == ["A", "B", "C"]