"""Тесты src.statements."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db import init_db
from src.db.models import Account, Statement as DBStatement, Transaction
from src.statements.crud import (
    DeleteStatementResult,
    delete_statement,
    get_statement,
    get_statement_by_file_hash,
    list_statements,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

_stmt_counter = [0]


def mk_stmt(session, **kwargs) -> DBStatement:
    _stmt_counter[0] += 1
    defaults = dict(
        account_id=1,
        file_name=f"x-{_stmt_counter[0]}.pdf",
        file_hash=f"fh-{_stmt_counter[0]}",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    defaults.update(kwargs)
    s = DBStatement(**defaults)
    session.add(s)
    session.flush()
    return s


def mk_tx(session, statement_id: int, tx_hash: str) -> Transaction:
    tx = Transaction(
        account_id=1, statement_id=statement_id,
        date=date(2024, 1, 15), amount=-100, currency="RUB",
        description="x", transaction_hash=tx_hash,
        hash_version=1, source="pdf",
    )
    session.add(tx)
    session.flush()
    return tx


# ---------------------------------------------------------------------------
# get_*
# ---------------------------------------------------------------------------

def test_get_statement_found(session):
    s = mk_stmt(session)
    assert get_statement(session, s.statement_id).statement_id == s.statement_id


def test_get_statement_not_found(session):
    assert get_statement(session, 999) is None


def test_get_by_file_hash_found(session):
    s = mk_stmt(session, file_hash="abc")
    found = get_statement_by_file_hash(session, "abc")
    assert found is not None
    assert found.statement_id == s.statement_id


def test_get_by_file_hash_not_found(session):
    assert get_statement_by_file_hash(session, "missing") is None


# ---------------------------------------------------------------------------
# list_statements
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert list_statements(session) == []


def test_list_by_account(session):
    mk_stmt(session, account_id=1)
    mk_stmt(session, account_id=2)
    assert len(list_statements(session, account_id=1)) == 1
    assert len(list_statements(session, account_id=2)) == 1


def test_list_sorting_by_period(session):
    a = mk_stmt(session, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31))
    b = mk_stmt(session, period_start=date(2024, 3, 1), period_end=date(2024, 3, 31))
    c = mk_stmt(session, period_start=date(2024, 2, 1), period_end=date(2024, 2, 29))
    ids = [s.statement_id for s in list_statements(session)]
    assert ids == [b.statement_id, c.statement_id, a.statement_id]


def test_list_pagination(session):
    for _ in range(5):
        mk_stmt(session)
    page1 = list_statements(session, limit=2, offset=0)
    page2 = list_statements(session, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {s.statement_id for s in page1}.isdisjoint(
        {s.statement_id for s in page2}
    )


def test_list_invalid_limit(session):
    with pytest.raises(ValueError):
        list_statements(session, limit=0)
    with pytest.raises(ValueError):
        list_statements(session, offset=-1)


# ---------------------------------------------------------------------------
# delete_statement — cascade_transactions=True
# ---------------------------------------------------------------------------

def test_delete_with_cascade(session):
    """delete_statement(cascade_transactions=True): удаляются
    statement и ВСЕ его транзакции."""
    s = mk_stmt(session)
    tx1 = mk_tx(session, s.statement_id, "h1")
    tx2 = mk_tx(session, s.statement_id, "h2")
    sid = s.statement_id
    tx_ids = (tx1.transaction_id, tx2.transaction_id)

    result = delete_statement(session, sid)

    assert isinstance(result, DeleteStatementResult)
    assert result.statement_id == sid
    assert result.deleted_transactions == 2
    assert result.unlinked_transactions == 0

    session.expire_all()
    assert get_statement(session, sid) is None
    for tx_id in tx_ids:
        assert session.get(Transaction, tx_id) is None


# ---------------------------------------------------------------------------
# delete_statement — cascade_transactions=False (FK ON DELETE SET NULL)
# ---------------------------------------------------------------------------

def test_delete_without_cascade(session):
    """delete_statement(cascade_transactions=False): statement удаляется,
    транзакции остаются с statement_id=NULL (делает БД через SET NULL)."""
    s = mk_stmt(session)
    tx1 = mk_tx(session, s.statement_id, "h1")
    sid = s.statement_id
    tx_id = tx1.transaction_id

    result = delete_statement(session, sid, cascade_transactions=False)

    assert result.deleted_transactions == 0
    assert result.unlinked_transactions == 1

    session.expire_all()
    assert get_statement(session, sid) is None
    tx = session.get(Transaction, tx_id)
    assert tx is not None
    assert tx.statement_id is None
    assert tx.account_id == 1  # account_id не тронут


def test_delete_without_cascade_when_collection_loaded(session):
    """Регрессия: passive_deletes=True при загруженной коллекции
    удалял детей даже при cascade_transactions=False.
    С passive_deletes="all" + FK SET NULL данные должны сохраниться."""
    s = mk_stmt(session)
    tx1 = mk_tx(session, s.statement_id, "h1")
    tx2 = mk_tx(session, s.statement_id, "h2")
    sid = s.statement_id
    tx_ids = (tx1.transaction_id, tx2.transaction_id)

    # Намеренно грузим коллекцию ДО delete_statement — это тот самый
    # путь, на котором старый код терял данные.
    loaded = session.get(DBStatement, sid)
    assert len(loaded.transactions) == 2

    delete_statement(session, sid, cascade_transactions=False)
    session.expire_all()

    assert get_statement(session, sid) is None
    for tx_id in tx_ids:
        tx = session.get(Transaction, tx_id)
        assert tx is not None
        assert tx.statement_id is None


# ---------------------------------------------------------------------------
# Прочее
# ---------------------------------------------------------------------------

def test_delete_no_transactions(session):
    s = mk_stmt(session)
    result = delete_statement(session, s.statement_id)
    assert result.deleted_transactions == 0
    assert result.unlinked_transactions == 0


def test_delete_not_found(session):
    with pytest.raises(ValueError):
        delete_statement(session, 999)


def test_delete_does_not_touch_other_statements(session):
    s1 = mk_stmt(session)
    s2 = mk_stmt(session)
    mk_tx(session, s1.statement_id, "h1")
    tx2 = mk_tx(session, s2.statement_id, "h2")
    tx2_id = tx2.transaction_id
    s2_id = s2.statement_id

    delete_statement(session, s1.statement_id)

    session.expire_all()
    assert get_statement(session, s2_id) is not None
    assert session.get(Transaction, tx2_id) is not None


def test_delete_then_can_reimport_same_file_hash(session):
    """Сценарий: удалили → file_hash свободен → можно импортировать снова."""
    s = mk_stmt(session, file_hash="reimport-me")
    delete_statement(session, s.statement_id)
    assert get_statement_by_file_hash(session, "reimport-me") is None