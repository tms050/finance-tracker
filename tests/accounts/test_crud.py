"""Тесты src.accounts.crud."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src._internal.sentinel import UNSET
from src.accounts.crud import (
    DeleteAccountResult,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)
from src.db import init_db
from src.db.models import Account, Statement, Transaction


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


def _mk(session, **kwargs) -> Account:
    defaults = dict(
        bank_name="Sber",
        account_name="Main",
        account_number_masked="**** 0001",
        currency="RUB",
    )
    defaults.update(kwargs)
    return create_account(session, **defaults)


def _add_tx(session, account_id: int, tx_hash: str, currency: str = "RUB") -> Transaction:
    tx = Transaction(
        account_id=account_id, date=date(2024, 1, 15), amount=-100,
        currency=currency, description="x", transaction_hash=tx_hash,
        hash_version=1, source="pdf",
    )
    session.add(tx)
    session.flush()
    return tx


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------

def test_get_found(session):
    a = _mk(session)
    assert get_account(session, a.account_id).account_id == a.account_id


def test_get_not_found(session):
    assert get_account(session, 999) is None


# ---------------------------------------------------------------------------
# create_account
# ---------------------------------------------------------------------------

def test_create_ok(session):
    a = _mk(session)
    assert a.account_id is not None
    assert a.currency == "RUB"


def test_create_strips_and_uppers(session):
    a = _mk(session, bank_name="  Sber  ", currency="rub")
    assert a.bank_name == "Sber"
    assert a.currency == "RUB"


def test_create_empty_bank_name(session):
    with pytest.raises(ValueError):
        _mk(session, bank_name="   ")


def test_create_empty_account_number(session):
    with pytest.raises(ValueError):
        _mk(session, account_number_masked="")


# ---------------------------------------------------------------------------
# list_accounts
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert list_accounts(session) == []


def test_list_sorting(session):
    _mk(session, bank_name="Tinkoff", account_name="B")
    _mk(session, bank_name="Alfa", account_name="X")
    _mk(session, bank_name="Sber", account_name="A")
    names = [(a.bank_name, a.account_name) for a in list_accounts(session)]
    assert names == [("Alfa", "X"), ("Sber", "A"), ("Tinkoff", "B")]


# ---------------------------------------------------------------------------
# update_account
# ---------------------------------------------------------------------------

def test_update_partial(session):
    a = _mk(session)
    update_account(session, a.account_id, account_name="New")
    session.refresh(a)
    assert a.account_name == "New"
    assert a.bank_name == "Sber"


def test_update_noop_unset(session):
    a = _mk(session)
    update_account(session, a.account_id)
    session.refresh(a)
    assert a.account_name == "Main"


def test_update_not_found(session):
    with pytest.raises(ValueError):
        update_account(session, 999, account_name="X")


def test_update_currency_no_transactions(session):
    a = _mk(session)
    update_account(session, a.account_id, currency="USD")
    session.refresh(a)
    assert a.currency == "USD"


def test_update_currency_conflict(session):
    a = _mk(session)
    _add_tx(session, a.account_id, "h1", currency="RUB")
    with pytest.raises(ValueError, match="another currency"):
        update_account(session, a.account_id, currency="USD")


def test_update_currency_to_multi_ok(session):
    a = _mk(session)
    _add_tx(session, a.account_id, "h1", currency="RUB")
    update_account(session, a.account_id, currency="MULTI")
    session.refresh(a)
    assert a.currency == "MULTI"


def test_update_fio_to_none(session):
    a = _mk(session, fio="Ivanov")
    update_account(session, a.account_id, fio=None)
    session.refresh(a)
    assert a.fio is None


# ---------------------------------------------------------------------------
# delete_account
# ---------------------------------------------------------------------------

def test_delete_empty_no_cascade(session):
    a = _mk(session)
    result = delete_account(session, a.account_id)
    assert isinstance(result, DeleteAccountResult)
    assert result.deleted_statements == 0
    assert result.deleted_transactions == 0
    session.expire_all()
    assert get_account(session, a.account_id) is None


def test_delete_with_data_no_cascade_raises(session):
    a = _mk(session)
    _add_tx(session, a.account_id, "h1")
    with pytest.raises(ValueError, match="cascade=True"):
        delete_account(session, a.account_id)


def test_delete_with_cascade(session):
    a = _mk(session)
    stmt = Statement(
        account_id=a.account_id, file_name="x.pdf", file_hash="fh1",
        period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
    )
    session.add(stmt)
    session.flush()
    _add_tx(session, a.account_id, "h1")
    _add_tx(session, a.account_id, "h2")

    stmt_id = stmt.statement_id
    account_id = a.account_id

    result = delete_account(session, a.account_id, cascade=True)
    assert result.deleted_statements == 1
    assert result.deleted_transactions == 2

    session.expire_all()
    assert get_account(session, account_id) is None
    assert session.get(Statement, stmt_id) is None

def test_delete_not_found(session):
    with pytest.raises(ValueError):
        delete_account(session, 999)