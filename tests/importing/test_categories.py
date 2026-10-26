"""Тесты B2b: категории."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.db import init_db
from src.db.models import (
    Account,
    Category,
    Statement as DBStatement,
    Transaction as DBTransaction,
)
from src.importing.categories import (
    find_or_create_category,
    import_with_categories,
    infer_category_type,
)

from src.categories.crud import create_category  
from src.importing.categories import (         
    find_or_create_category,
    import_with_categories,
    infer_category_type,
)

from src.importing.import_to_db import import_prepared_statement
from src.importing.prepare import PreparedStatement, PreparedTransaction


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
    is_transfer=False,
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
        is_transfer=is_transfer,
        transaction_hash=transaction_hash,
        hash_version=1,
        source="pdf",
        original_index=original_index,
        is_valid=True,
        validation_errors=(),
    )


def make_prepared(**kwargs) -> PreparedStatement:
    defaults = dict(
        file_name="test.pdf",
        file_hash="fh1",
        account_id=1,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        transactions_to_insert=(),
        rejected=(),
        intra_batch_collisions=(),
        warnings=(),
        balance_check=None,
        _raw_statement_info=None,
    )
    defaults.update(kwargs)
    return PreparedStatement(**defaults)


# ---------------------------------------------------------------------------
# infer_category_type
# ---------------------------------------------------------------------------

def test_infer_transfer_priority():
    assert infer_category_type(-100, is_transfer=True) == "transfer"
    assert infer_category_type(100, is_transfer=True) == "transfer"
    assert infer_category_type(0, is_transfer=True) == "transfer"


def test_infer_expense_negative():
    assert infer_category_type(-100, is_transfer=False) == "expense"


def test_infer_income_positive():
    assert infer_category_type(100, is_transfer=False) == "income"


def test_infer_zero_is_expense():
    assert infer_category_type(0, is_transfer=False) == "expense"


def test_infer_none_is_expense():
    assert infer_category_type(None, is_transfer=False) == "expense"


# ---------------------------------------------------------------------------
# find_or_create_category
# ---------------------------------------------------------------------------

def test_find_or_create_creates(session):
    category, created, warnings = find_or_create_category(
        session, "Супермаркеты", "expense"
    )
    assert created is True
    assert warnings == []
    assert category.category_id is not None
    assert category.name == "Супермаркеты"
    assert category.type == "expense"


def test_find_or_create_reuses_same_type(session):
    c1, _, _ = find_or_create_category(session, "X", "expense")
    c2, created, warnings = find_or_create_category(session, "X", "expense")
    assert created is False
    assert warnings == []
    assert c1.category_id == c2.category_id


def test_find_or_create_reuses_with_type_warning(session):
    find_or_create_category(session, "X", "expense")
    c2, created, warnings = find_or_create_category(session, "X", "income")
    assert created is False
    assert len(warnings) == 1
    assert "expense" in warnings[0] and "income" in warnings[0]


def test_find_or_create_case_sensitive(session):
    c1, _, _ = find_or_create_category(session, "Супермаркеты", "expense")
    c2, _, _ = find_or_create_category(session, "супермаркеты", "expense")
    assert c1.category_id != c2.category_id


def test_find_or_create_empty_name_raises(session):
    with pytest.raises(ValueError):
        find_or_create_category(session, "", "expense")
    with pytest.raises(ValueError):
        find_or_create_category(session, "   ", "expense")


def test_find_or_create_parent_matters(session):
    parent = create_category(session, "Food", "expense")
    c1, _, _ = find_or_create_category(session, "Coffee", "expense", parent.category_id)
    c2, _, _ = find_or_create_category(session, "Coffee", "expense", None)
    assert c1.category_id != c2.category_id


# ---------------------------------------------------------------------------
# import_with_categories
# ---------------------------------------------------------------------------

def test_import_with_categories_happy(session):
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", original_index=0, raw_category="A"),
        make_pretx("h2", original_index=1, raw_category="B"),
    ))
    result = import_with_categories(session, prepared)

    assert result.status == "ok"
    assert len(result.inserted_transactions) == 2
    assert len(result.created_categories) == 2

    txs = session.execute(select(DBTransaction)).scalars().all()
    assert all(tx.category_id is not None for tx in txs)


def test_import_with_categories_disabled(session):
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", raw_category="A"),
    ))
    result = import_with_categories(
        session, prepared, auto_create_categories=False
    )
    assert result.created_categories == ()

    tx = session.execute(select(DBTransaction)).scalar_one()
    assert tx.category_id is None
    assert tx.raw_category == "A"

    cat_count = session.execute(select(func.count(Category.category_id))).scalar()
    assert cat_count == 0


def test_import_with_categories_no_raw(session):
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", raw_category=None),
    ))
    result = import_with_categories(session, prepared)
    assert result.created_categories == ()
    cat_count = session.execute(select(func.count(Category.category_id))).scalar()
    assert cat_count == 0


def test_import_with_categories_blank_raw(session):
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", raw_category="   "),
    ))
    result = import_with_categories(session, prepared)
    assert result.created_categories == ()


def test_import_with_categories_type_conflict_warns(session):
    # Пред-создаём категорию с типом income
    create_category(session, "Salary", "income")
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", amount=-100, raw_category="Salary"),  # inferred expense
    ))
    result = import_with_categories(session, prepared)

    assert result.created_categories == ()  # переиспользована
    assert any("Salary" in w and "income" in w for w in result.warnings)


def test_import_with_categories_duplicate_statement_no_categories(session):
    prepared1 = make_prepared(
        file_hash="same",
        transactions_to_insert=(make_pretx("h1", raw_category="A"),),
    )
    import_with_categories(session, prepared1)

    prepared2 = make_prepared(
        file_hash="same",   # тот же file_hash
        transactions_to_insert=(make_pretx("h2", raw_category="B"),),
    )
    result = import_with_categories(session, prepared2)

    assert result.status == "duplicate_statement"
    assert result.created_categories == ()
    # Категория "B" НЕ должна создаться
    names = {c.name for c in session.execute(select(Category)).scalars()}
    assert names == {"A"}


def test_import_with_categories_no_valid_no_categories(session):
    prepared = make_prepared(transactions_to_insert=())
    result = import_with_categories(session, prepared)
    assert result.status == "no_valid_transactions"
    assert result.created_categories == ()


def test_import_with_categories_reuses_across_imports(session):
    p1 = make_prepared(
        file_hash="fh1",
        transactions_to_insert=(make_pretx("h1", raw_category="A"),),
    )
    r1 = import_with_categories(session, p1)
    assert len(r1.created_categories) == 1

    p2 = make_prepared(
        file_hash="fh2",
        transactions_to_insert=(make_pretx("h2", raw_category="A"),),
    )
    r2 = import_with_categories(session, p2)
    assert r2.created_categories == ()  # переиспользована

    cat_count = session.execute(select(func.count(Category.category_id))).scalar()
    assert cat_count == 1


def test_import_with_categories_rollback_reverts_all(session):
    prepared = make_prepared(transactions_to_insert=(
        make_pretx("h1", raw_category="A"),
    ))
    import_with_categories(session, prepared)
    session.rollback()

    assert session.execute(select(func.count(Category.category_id))).scalar() == 0
    assert session.execute(select(func.count(DBTransaction.transaction_id))).scalar() == 0
    assert session.execute(select(func.count(DBStatement.statement_id))).scalar() == 0