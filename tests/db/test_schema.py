# tests/db/test_schema.py
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.db.factories import (
    make_account,
    make_category,
    make_statement,
    make_transaction,
)


# --- Создание схемы ---------------------------------------------------------

def test_create_all_creates_expected_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {"accounts", "statements", "transactions", "categories"} <= tables


def test_schema_version_table_exists(engine):
    assert "schema_version" in inspect(engine).get_table_names()


def test_init_db_is_idempotent(engine):
    from src.db.init import init_db
    init_db(engine)  # второй вызов не должен упасть
    init_db(engine)


# --- PRAGMA (проверяем, что listener из engine.py сработал) ----------------

def test_foreign_keys_pragma_is_on(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_busy_timeout_pragma(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000


# --- UNIQUE: statements.file_hash ------------------------------------------

def test_unique_file_hash(session):
    account = make_account(session)
    make_statement(session, account, file_hash="dup")
    make_statement(session, account, file_hash="dup", file_name="other.pdf", flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- UNIQUE: transactions (account_id, transaction_hash) -------------------

def test_unique_account_transaction_hash(session):
    account = make_account(session)
    make_transaction(session, account, transaction_hash="dup")
    make_transaction(session, account, transaction_hash="dup", flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_hash_allowed_on_different_accounts(session):
    a1 = make_account(session, account_number_masked="****1111")
    a2 = make_account(session, account_number_masked="****2222")
    make_transaction(session, a1, transaction_hash="same-hash")
    make_transaction(session, a2, transaction_hash="same-hash")
    session.commit()


# --- UNIQUE: accounts (bank_name, account_number_masked) -------------------

def test_accounts_unique_bank_and_number(session):
    make_account(session, bank_name="Sber", account_number_masked="****1111")
    make_account(session, bank_name="Sber", account_number_masked="****1111", flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_accounts_same_number_different_banks_allowed(session):
    make_account(session, bank_name="Sber", account_number_masked="****1111")
    make_account(session, bank_name="Tinkoff", account_number_masked="****1111")
    session.commit()


# --- CHECK: currency --------------------------------------------------------

@pytest.mark.parametrize("bad_currency", ["GBP", "rub", "", "MULTI"])
def test_transactions_currency_check(session, bad_currency):
    account = make_account(session)
    make_transaction(session, account, currency=bad_currency, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_accounts_currency_check(session):
    make_account(session, currency="GBP", flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_accounts_currency_allows_multi(session):
    make_account(session, currency="MULTI")
    session.commit()


# --- CHECK: source, is_transfer, hash_version ------------------------------

@pytest.mark.parametrize("bad_source", ["file", "", "PDF"])
def test_transactions_source_check(session, bad_source):
    account = make_account(session)
    make_transaction(session, account, source=bad_source, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("bad_value", [2, -1, 42])
def test_transactions_is_transfer_check(session, bad_value):
    account = make_account(session)
    make_transaction(session, account, is_transfer=bad_value, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_transactions_hash_version_check(session):
    account = make_account(session)
    make_transaction(session, account, hash_version=0, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- CHECK: categories.type -------------------------------------------------

@pytest.mark.parametrize("bad_type", ["transfer_in", "", "Expense"])
def test_categories_type_check(session, bad_type):
    make_category(session, type=bad_type, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- CHECK: даты ------------------------------------------------------------

def test_accounts_dates_order_check(session):
    make_account(
        session,
        open_date=date(2026, 5, 1),
        close_date=date(2026, 1, 1),  # раньше open_date
        flush=False,
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_statement_period_order_check(session):
    account = make_account(session)
    make_statement(
        session,
        account,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 1, 1),
        flush=False,
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_statement_period_order_null_allowed(session):
    """Проверка должна пропускать случай, когда одна из дат NULL."""
    account = make_account(session)
    make_statement(session, account, period_start=date(2026, 1, 1), period_end=None)
    make_statement(session, account, period_start=None, period_end=date(2026, 1, 1))
    session.commit()


# --- UNIQUE(name, parent_category_id) для дочерних -------------------------

def test_categories_unique_name_per_parent(session):
    parent = make_category(session, name="Food")
    make_category(session, name="Snacks", parent_category_id=parent.category_id)
    make_category(
        session, name="Snacks", parent_category_id=parent.category_id, flush=False
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- Partial UNIQUE index для корневых категорий ---------------------------

def test_root_categories_unique_name(session):
    """NULL != NULL в SQL — поэтому нужен partial index."""
    make_category(session, name="Продукты", parent_category_id=None)
    make_category(session, name="Продукты", parent_category_id=None, flush=False)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_root_categories_different_names_allowed(session):
    make_category(session, name="Продукты", parent_category_id=None)
    make_category(session, name="Транспорт", parent_category_id=None)
    session.commit()


def test_same_name_allowed_for_root_and_child_of_other_parent(session):
    """'Продукты' можно иметь и как корень, и как ребёнка у другого родителя."""
    make_category(session, name="Продукты", parent_category_id=None)
    parent2 = make_category(session, name="Транспорт", parent_category_id=None)
    make_category(session, name="Продукты", parent_category_id=parent2.category_id)
    session.commit()