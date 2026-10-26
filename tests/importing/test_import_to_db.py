"""Тесты B2a на in-memory SQLite."""

from __future__ import annotations

import dataclasses
from datetime import date, time

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.db import init_db
from src.db.models import Statement as DBStatement, Transaction as DBTransaction
from src.importing.import_to_db import (
    CrossBatchSkip,
    ImportResult,
    IntraBatchSkip,
    import_prepared_statement,
)
from src.importing.prepare import (
    IntraBatchCollision,
    PreparedStatement,
    PreparedTransaction,
)

from src.db.models import Account


# ---------------------------------------------------------------------------
# Фикстуры / хелперы
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        s.add(Account(
            account_id=1,
            bank_name="Sber",
            account_name="Test",
            account_number_masked="**** 0000",
            currency="RUB",
        ))
        s.commit()
        yield s
        s.rollback()


def make_pretx(
    transaction_hash="h1",
    *,
    original_index=0,
    account_id=1,
    amount=-15000,
    description="test",
    raw_category=None,
) -> PreparedTransaction:
    return PreparedTransaction(
        account_id=account_id,
        statement_id=None,
        date=date(2024, 1, 15),
        time=time(12, 34),
        amount=amount,
        currency="RUB",
        description=description,
        counterparty_name=None,
        category_id=None,
        authorization_code=None,
        raw_category=raw_category,
        is_transfer=False,
        transaction_hash=transaction_hash,
        hash_version=1,
        source="pdf",
        original_index=original_index,
        is_valid=True,
        validation_errors=(),
    )


def make_prepared(
    *,
    file_hash="fh1",
    account_id=1,
    to_insert=(),
    rejected=(),
    collisions=(),
    warnings=(),
) -> PreparedStatement:
    return PreparedStatement(
        file_name="test.pdf",
        file_hash=file_hash,
        account_id=account_id,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        transactions_to_insert=tuple(to_insert),
        rejected=tuple(rejected),
        intra_batch_collisions=tuple(collisions),
        warnings=tuple(warnings),
        balance_check=None,
        _raw_statement_info=None,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path(session):
    prepared = make_prepared(
        to_insert=[make_pretx("h1", original_index=0),
                   make_pretx("h2", original_index=1)],
    )
    result = import_prepared_statement(session, prepared)

    assert result.status == "ok"
    assert result.statement_id is not None
    assert len(result.inserted_transactions) == 2
    assert result.skipped_intra_batch == ()
    assert result.skipped_cross_batch == ()
    assert result.created_categories == ()
    assert result.warnings == ()

    count = session.execute(
        select(func.count(DBTransaction.transaction_id))
    ).scalar()
    assert count == 2


# ---------------------------------------------------------------------------
# duplicate_statement / no_valid_transactions
# ---------------------------------------------------------------------------

def test_duplicate_statement(session):
    prepared = make_prepared(file_hash="same", to_insert=[make_pretx("h1")])
    r1 = import_prepared_statement(session, prepared)
    r2 = import_prepared_statement(session, prepared)

    assert r1.status == "ok"
    assert r2.status == "duplicate_statement"
    assert r2.statement_id == r1.statement_id
    assert r2.inserted_transactions == ()


def test_no_valid_transactions(session):
    prepared = make_prepared(to_insert=[], rejected=[make_pretx("h1")])
    result = import_prepared_statement(session, prepared)

    assert result.status == "no_valid_transactions"
    assert result.statement_id is None

    count = session.execute(
        select(func.count(DBStatement.statement_id))
    ).scalar()
    assert count == 0


# ---------------------------------------------------------------------------
# Intra-batch
# ---------------------------------------------------------------------------

def test_intra_batch_collision_keeps_first_by_original_index(session):
    # нюанс 2: «самая ранняя» по original_index — tx0 (raw_category="A")
    tx0 = make_pretx("h1", original_index=0, raw_category="A")
    tx1 = make_pretx("h1", original_index=1, raw_category="B")
    collision = IntraBatchCollision(transaction_hash="h1", transactions=(tx0, tx1))
    prepared = make_prepared(to_insert=[tx0, tx1], collisions=[collision])

    result = import_prepared_statement(session, prepared)

    assert result.status == "ok"
    assert len(result.inserted_transactions) == 1
    assert len(result.skipped_intra_batch) == 1
    skip = result.skipped_intra_batch[0]
    assert isinstance(skip, IntraBatchSkip)
    assert skip.original_index == 1
    assert skip.transaction_hash == "h1"

    # В БД — именно tx0 (raw_category="A")
    raw_cat = session.execute(select(DBTransaction.raw_category)).scalar_one()
    assert raw_cat == "A"


def test_all_intra_skipped_status_ok_with_warning(session):
    # Одна группа коллизий, оставляем первую → 1 вставлена, 1 skip.
    # Чтобы получить all-skipped через intra-batch, нужна ситуация,
    # где ВСЕ попали в skip — это возможно только через cross-batch (ниже).
    # Здесь проверяем частичный skip + warning.
    tx0 = make_pretx("h1", original_index=0)
    tx1 = make_pretx("h1", original_index=1)
    collision = IntraBatchCollision(transaction_hash="h1", transactions=(tx0, tx1))
    prepared = make_prepared(to_insert=[tx0, tx1], collisions=[collision])

    result = import_prepared_statement(session, prepared)

    assert result.status == "ok"
    assert len(result.inserted_transactions) == 1
    assert any("Пропущено 1" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Cross-batch
# ---------------------------------------------------------------------------

def test_cross_batch_conflict(session):
    p1 = make_prepared(file_hash="fh1", to_insert=[make_pretx("h1", original_index=0)])
    r1 = import_prepared_statement(session, p1)
    existing_id = r1.inserted_transactions[0]

    p2 = make_prepared(file_hash="fh2", to_insert=[make_pretx("h1", original_index=0)])
    r2 = import_prepared_statement(session, p2)

    assert r2.status == "ok"
    assert r2.inserted_transactions == ()
    assert len(r2.skipped_cross_batch) == 1
    skip = r2.skipped_cross_batch[0]
    assert isinstance(skip, CrossBatchSkip)
    assert skip.existing_transaction_id == existing_id
    assert skip.transaction_hash == "h1"

    # Statement создан, несмотря на all-skip
    assert r2.statement_id is not None

    # Повторный импорт p2 → duplicate_statement
    r3 = import_prepared_statement(session, p2)
    assert r3.status == "duplicate_statement"
    assert r3.statement_id == r2.statement_id


def test_cross_batch_chunking(session):
    # 100 в первом
    first_txs = [make_pretx(f"h{i}", original_index=i) for i in range(100)]
    p1 = make_prepared(file_hash="fh1", to_insert=first_txs)
    r1 = import_prepared_statement(session, p1)
    assert len(r1.inserted_transactions) == 100

    # 1200 во втором: 100 существующих + 1100 новых → chunking (500 + 500 + 200)
    second_txs = [make_pretx(f"h{i}", original_index=i) for i in range(100)]
    second_txs += [
        make_pretx(f"new{i}", original_index=100 + i) for i in range(1100)
    ]
    p2 = make_prepared(file_hash="fh2", to_insert=second_txs)
    r2 = import_prepared_statement(session, p2, chunk_size=500)

    assert len(r2.skipped_cross_batch) == 100
    assert len(r2.inserted_transactions) == 1100


# ---------------------------------------------------------------------------
# Валидация / rollback / unit of work
# ---------------------------------------------------------------------------

def test_account_id_none_raises(session):
    prepared = make_prepared(to_insert=[make_pretx("h1")])
    prepared_none = dataclasses.replace(prepared, account_id=None)
    with pytest.raises(ValueError):
        import_prepared_statement(session, prepared_none)


def test_chunk_size_invalid_raises(session):
    prepared = make_prepared(to_insert=[make_pretx("h1")])
    with pytest.raises(ValueError):
        import_prepared_statement(session, prepared, chunk_size=0)


def test_rollback_reverts_everything(session):
    prepared = make_prepared(to_insert=[make_pretx("h1")])
    import_prepared_statement(session, prepared)
    session.rollback()

    tx_count = session.execute(
        select(func.count(DBTransaction.transaction_id))
    ).scalar()
    stmt_count = session.execute(
        select(func.count(DBStatement.statement_id))
    ).scalar()
    assert tx_count == 0
    assert stmt_count == 0


def test_unit_of_work_two_imports(session):
    p1 = make_prepared(file_hash="fh1", to_insert=[make_pretx("h1")])
    p2 = make_prepared(file_hash="fh2", to_insert=[make_pretx("h2")])
    r1 = import_prepared_statement(session, p1)
    r2 = import_prepared_statement(session, p2)

    assert r1.status == "ok"
    assert r2.status == "ok"
    session.commit()

    count = session.execute(
        select(func.count(DBTransaction.transaction_id))
    ).scalar()
    assert count == 2