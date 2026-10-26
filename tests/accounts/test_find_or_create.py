"""Тесты src.accounts.find_or_create."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.accounts.find_or_create import find_or_create_account
from src.db import init_db


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


def test_creates_when_missing(session):
    account, created, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        account_name="Main", currency="RUB",
    )
    assert created is True
    assert warnings == []
    assert account.account_id is not None
    assert account.currency == "RUB"


def test_finds_existing(session):
    a1, _, _ = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
    )
    a2, created, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
    )
    assert created is False
    assert warnings == []
    assert a1.account_id == a2.account_id


def test_currency_conflict_warns(session):
    find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        currency="RUB",
    )
    a, created, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        currency="USD",
    )
    assert created is False
    assert any("валюта" in w and "USD" in w for w in warnings)


def test_fio_conflict_warns(session):
    find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        fio="Ivanov",
    )
    a, created, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        fio="Petrov",
    )
    assert created is False
    assert any("ФИО" in w and "Petrov" in w for w in warnings)


def test_no_fio_no_warning(session):
    """Если fio не передан — расхождение не проверяется."""
    find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        fio="Ivanov",
    )
    a, created, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
    )
    assert created is False
    assert warnings == []


def test_open_date_conflict_warns(session):
    find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        open_date=date(2020, 1, 1),
    )
    a, _, warnings = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
        open_date=date(2021, 1, 1),
    )
    assert any("дата открытия" in w for w in warnings)


def test_different_number_creates_separate(session):
    a1, _, _ = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0001",
    )
    a2, created, _ = find_or_create_account(
        session, bank_name="Sber", account_number_masked="**** 0002",
    )
    assert created is True
    assert a1.account_id != a2.account_id


def test_empty_bank_name_raises(session):
    with pytest.raises(ValueError):
        find_or_create_account(
            session, bank_name="  ", account_number_masked="**** 0001",
        )


def test_empty_account_number_raises(session):
    with pytest.raises(ValueError):
        find_or_create_account(
            session, bank_name="Sber", account_number_masked="",
        )