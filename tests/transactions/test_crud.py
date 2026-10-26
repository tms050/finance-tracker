"""Тесты B2c: CRUD транзакций."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db import init_db
from src.db.models import (
    Account,
    Category,
    Statement as DBStatement,
    Transaction,
)
from src.categories import create_category
from src.importing.prepare import prepare_transaction
from src.transactions.crud import (
    DuplicateTransactionError,
    add_manual_transaction,
    count_transactions,
    delete_transaction,
    get_transaction,
    list_transactions,
    update_transaction,
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
                account_id=1, bank_name="Sber", account_name="RUB",
                account_number_masked="**** 0001", currency="RUB",
            ),
            Account(
                account_id=2, bank_name="Sber", account_name="Multi",
                account_number_masked="**** 0002", currency="MULTI",
            ),
        ])
        s.commit()
        yield s
        s.rollback()


# ---------------------------------------------------------------------------
# add_manual_transaction
# ---------------------------------------------------------------------------

class TestAddManual:
    def test_happy_rub(self, session):
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
            description="coffee",
        )
        assert tx.transaction_id is not None
        assert tx.currency == "RUB"
        assert tx.source == "manual"
        assert tx.statement_id is None
        assert tx.hash_version == 1

    def test_with_time(self, session):
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15),
            time=time(14, 30), amount=-15000,
        )
        assert tx.time == time(14, 30)

    def test_without_time(self, session):
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        )
        assert tx.time is None

    def test_multi_no_currency(self, session):
        with pytest.raises(ValueError, match="currency_none_multi"):
            add_manual_transaction(
                session, account_id=2, date=date(2024, 1, 15), amount=-15000,
            )

    def test_multi_with_currency(self, session):
        tx = add_manual_transaction(
            session, account_id=2, date=date(2024, 1, 15), amount=-15000,
            currency="USD",
        )
        assert tx.currency == "USD"

    def test_rub_mismatch(self, session):
        with pytest.raises(ValueError, match="currency_mismatch"):
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 15), amount=-15000,
                currency="USD",
            )

    def test_account_missing(self, session):
        with pytest.raises(ValueError, match="account"):
            add_manual_transaction(
                session, account_id=999, date=date(2024, 1, 15), amount=-15000,
            )

    def test_category_missing(self, session):
        with pytest.raises(ValueError, match="category"):
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 15), amount=-15000,
                category_id=999,
            )

    def test_category_set(self, session):
        cat = create_category(session, "Food", "expense")
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
            category_id=cat.category_id,
        )
        assert tx.category_id == cat.category_id

    def test_duplicate_raises(self, session):
        tx1 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
            description="x",
        )
        with pytest.raises(DuplicateTransactionError) as ei:
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 15), amount=-15000,
                description="x",
            )
        assert ei.value.existing_transaction_id == tx1.transaction_id
        assert ei.value.transaction_hash == tx1.transaction_hash

    def test_hash_matches_b1(self, session):
        b1 = prepare_transaction(
            account_id=1, account_currency="RUB",
            date=date(2024, 1, 15), time=None, amount=-15000,
            description="test", counterparty_name=None,
            auth=None, category="",
        )
        assert b1.is_valid
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
            description="test",
        )
        assert tx.transaction_hash == b1.transaction_hash


# ---------------------------------------------------------------------------
# update_transaction
# ---------------------------------------------------------------------------

class TestUpdate:
    def _mk(self, session, **kwargs):
        defaults = dict(
            account_id=1, date=date(2024, 1, 15), amount=-15000,
            description="original",
        )
        defaults.update(kwargs)
        return add_manual_transaction(session, **defaults)

    def test_change_description(self, session):
        tx = self._mk(session)
        updated = update_transaction(
            session, tx.transaction_id, description="new"
        )
        assert updated.description == "new"

    def test_change_category(self, session):
        cat = create_category(session, "Food", "expense")
        tx = self._mk(session)
        updated = update_transaction(
            session, tx.transaction_id, category_id=cat.category_id
        )
        assert updated.category_id == cat.category_id

    def test_clear_category(self, session):
        cat = create_category(session, "Food", "expense")
        tx = self._mk(session, category_id=cat.category_id)
        updated = update_transaction(
            session, tx.transaction_id, category_id=None
        )
        assert updated.category_id is None

    def test_counterparty_empty_to_none(self, session):
        tx = self._mk(session, counterparty_name="X")
        updated = update_transaction(
            session, tx.transaction_id, counterparty_name=""
        )
        assert updated.counterparty_name is None

    def test_is_transfer_toggle(self, session):
        tx = self._mk(session)
        updated = update_transaction(
            session, tx.transaction_id, is_transfer=True
        )
        assert updated.is_transfer is True
        updated = update_transaction(
            session, tx.transaction_id, is_transfer=False
        )
        assert updated.is_transfer is False

    def test_partial_update_preserves_other_fields(self, session):
        tx = self._mk(session, counterparty_name="X")
        original_hash = tx.transaction_hash
        original_amount = tx.amount
        update_transaction(session, tx.transaction_id, description="new")
        session.refresh(tx)
        assert tx.amount == original_amount
        assert tx.counterparty_name == "X"
        assert tx.transaction_hash == original_hash

    def test_noop_all_unset(self, session):
        tx = self._mk(session)
        before = (
            tx.description, tx.category_id, tx.counterparty_name, tx.is_transfer,
        )
        update_transaction(session, tx.transaction_id)
        session.refresh(tx)
        assert (tx.description, tx.category_id, tx.counterparty_name,
                tx.is_transfer) == before

    def test_hash_unchanged(self, session):
        tx = self._mk(session)
        h, v = tx.transaction_hash, tx.hash_version
        update_transaction(
            session, tx.transaction_id,
            description="new", is_transfer=True, counterparty_name="Y",
        )
        session.refresh(tx)
        assert tx.transaction_hash == h
        assert tx.hash_version == v

    def test_missing_transaction(self, session):
        with pytest.raises(ValueError):
            update_transaction(session, 999, description="x")

    def test_missing_category(self, session):
        tx = self._mk(session)
        with pytest.raises(ValueError, match="category"):
            update_transaction(session, tx.transaction_id, category_id=999)

    def test_description_change_keeps_dedup(self, session):
        """Хэш — снимок на момент импорта; изменение description не
        позволяет повторно добавить ту же (оригинальную) транзакцию."""
        tx = self._mk(session)
        update_transaction(session, tx.transaction_id, description="edited")
        with pytest.raises(DuplicateTransactionError):
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 15),
                amount=-15000, description="original",
            )


# ---------------------------------------------------------------------------
# delete_transaction
# ---------------------------------------------------------------------------

class TestDelete:
    def test_ok(self, session):
        tx = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        )
        tx_id = tx.transaction_id
        delete_transaction(session, tx_id)
        assert get_transaction(session, tx_id) is None

    def test_missing(self, session):
        with pytest.raises(ValueError):
            delete_transaction(session, 999)

    def test_keeps_statement(self, session):
        stmt = DBStatement(
            account_id=1, file_name="x.pdf", file_hash="fh-keep",
            period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        )
        session.add(stmt)
        session.flush()
        tx = Transaction(
            account_id=1, statement_id=stmt.statement_id,
            date=date(2024, 1, 15), amount=-100, currency="RUB",
            description="x", transaction_hash="h-keep-1",
            hash_version=1, source="pdf",
        )
        session.add(tx)
        session.flush()
        tx_id, stmt_id = tx.transaction_id, stmt.statement_id

        delete_transaction(session, tx_id)
        session.expire_all()
        assert session.get(DBStatement, stmt_id) is not None
        assert session.get(Transaction, tx_id) is None


# ---------------------------------------------------------------------------
# get_transaction
# ---------------------------------------------------------------------------

def test_get_not_found(session):
    assert get_transaction(session, 999) is None


def test_get_ok(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
    )
    got = get_transaction(session, tx.transaction_id)
    assert got is not None
    assert got.transaction_id == tx.transaction_id


# ---------------------------------------------------------------------------
# list_transactions / count_transactions
# ---------------------------------------------------------------------------

class TestListCount:
    def test_empty(self, session):
        assert list_transactions(session) == []
        assert count_transactions(session) == 0

    def test_sorting(self, session):
        tx_early = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 1), time=time(10, 0),
            amount=-100,
        )
        tx_late1 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), time=time(9, 0),
            amount=-200,
        )
        tx_late2 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), time=time(15, 0),
            amount=-300,
        )
        txs = list_transactions(session, account_id=1)
        assert [t.transaction_id for t in txs] == [
            tx_late2.transaction_id,
            tx_late1.transaction_id,
            tx_early.transaction_id,
        ]

    def test_filter_by_account(self, session):
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-100,
        )
        add_manual_transaction(
            session, account_id=2, date=date(2024, 1, 15), amount=-200,
            currency="USD",
        )
        assert len(list_transactions(session, account_id=1)) == 1
        assert len(list_transactions(session, account_id=2)) == 1

    def test_filter_by_dates(self, session):
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 5), amount=-100,
        )
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-200,
        )
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 25), amount=-300,
        )
        assert len(list_transactions(
            session, date_from=date(2024, 1, 10),
        )) == 2
        assert len(list_transactions(
            session, date_to=date(2024, 1, 15),
        )) == 2
        assert len(list_transactions(
            session, date_from=date(2024, 1, 10),
            date_to=date(2024, 1, 20),
        )) == 1

    def test_filter_by_category(self, session):
        cat = create_category(session, "Food", "expense")
        tx1 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-100,
        )
        tx2 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 16), amount=-200,
        )
        update_transaction(session, tx2.transaction_id, category_id=cat.category_id)

        assert [t.transaction_id for t in list_transactions(
            session, category_id=cat.category_id,
        )] == [tx2.transaction_id]

    def test_filter_by_is_transfer(self, session):
        tx1 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-100,
        )
        tx2 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 16), amount=-200,
        )
        update_transaction(session, tx2.transaction_id, is_transfer=True)

        assert [t.transaction_id for t in list_transactions(
            session, is_transfer=True,
        )] == [tx2.transaction_id]
        assert [t.transaction_id for t in list_transactions(
            session, is_transfer=False,
        )] == [tx1.transaction_id]

    def test_pagination(self, session):
        for i in range(5):
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 1 + i),
                amount=-(i + 1) * 100,
            )
        page1 = list_transactions(session, limit=2, offset=0)
        page2 = list_transactions(session, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {t.transaction_id for t in page1}.isdisjoint(
            {t.transaction_id for t in page2}
        )

    def test_limit_invalid(self, session):
        with pytest.raises(ValueError):
            list_transactions(session, limit=0)
        with pytest.raises(ValueError):
            list_transactions(session, limit=-1)
        with pytest.raises(ValueError):
            list_transactions(session, offset=-1)

    def test_count_with_filters(self, session):
        cat = create_category(session, "Food", "expense")
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-100,
        )
        tx2 = add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 20), amount=-200,
        )
        update_transaction(session, tx2.transaction_id, category_id=cat.category_id)

        assert count_transactions(session) == 2
        assert count_transactions(session, category_id=cat.category_id) == 1
        assert count_transactions(session, date_from=date(2024, 1, 18)) == 1
        assert count_transactions(session, date_to=date(2024, 1, 18)) == 1


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def test_rollback_reverts(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
    )
    tx_id = tx.transaction_id
    session.rollback()
    assert get_transaction(session, tx_id) is None

def test_multi_unsupported_currency(session):
    """MULTI-счёт не должен пропускать GBP в БД."""
    with pytest.raises(ValueError, match="unsupported currency"):
        add_manual_transaction(
            session, account_id=2, date=date(2024, 1, 15),
            amount=-15000, currency="GBP",
        )


def test_prepare_unsupported_currency_in_pdf_path():
    """Парсер отдал неизвестную валюту — ошибка валидации, не IntegrityError."""
    from src.importing.prepare import prepare_transaction, ERR_CURRENCY_UNSUPPORTED
    p = prepare_transaction(
        account_id=1, account_currency="MULTI",
        date=date(2024, 1, 15), amount=-15000, currency="GBP",
        description="x", counterparty_name=None, auth=None, category="",
    )
    assert not p.is_valid
    assert ERR_CURRENCY_UNSUPPORTED in p.validation_errors

# tests/src/test_crud.py

def test_add_manual_description_empty_normalized(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        description="",
    )
    assert tx.description is None


def test_add_manual_description_whitespace_normalized(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        description="   ",
    )
    assert tx.description is None


def test_update_description_empty_normalized(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        description="original",
    )
    updated = update_transaction(session, tx.transaction_id, description="")
    assert updated.description is None


def test_update_description_whitespace_normalized(session):
    tx = add_manual_transaction(
        session, account_id=1, date=date(2024, 1, 15), amount=-15000,
        description="original",
    )
    updated = update_transaction(session, tx.transaction_id, description="   ")
    assert updated.description is None

# tests/src/test_crud.py

def test_multi_unsupported_currency_raises(session):
    with pytest.raises(ValueError, match="unsupported currency"):
        add_manual_transaction(
            session, account_id=2, date=date(2024, 1, 15),
            amount=-15000, currency="GBP",
        )


# tests/importing/test_prepare.py

def test_prepare_unsupported_currency():
    from src.importing.prepare import prepare_transaction, ERR_CURRENCY_UNSUPPORTED
    p = prepare_transaction(
        account_id=1, account_currency="MULTI",
        date=date(2024, 1, 15), amount=-15000, currency="GBP",
        description="x", counterparty_name=None, auth=None, category="",
    )
    assert not p.is_valid
    assert ERR_CURRENCY_UNSUPPORTED in p.validation_errors

# tests/src/test_crud.py
# tests/src/test_crud.py

# tests/src/test_crud.py

class TestSearch:
    """description_query в list_transactions и count_transactions."""

    def _seed(self, session):
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 15), amount=-100,
            description="Пятёрочка", counterparty_name="PYATEROCHKA",
        )
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 16), amount=-200,
            description="Кофейня", counterparty_name="COFFEE",
        )
        add_manual_transaction(
            session, account_id=1, date=date(2024, 1, 17), amount=-300,
            description=None, counterparty_name=None,
        )

    def test_search_by_description_cyrillic_ci(self, session):
        """Кириллица, регистр: 'пятёрочка' находит 'Пятёрочка'."""
        self._seed(session)
        assert len(list_transactions(
            session, description_query="пятёрочка",
        )) == 1

    def test_search_by_counterparty_latin_ci(self, session):
        """Латинский case-fold (было в исходном тесте, но с опечаткой)."""
        self._seed(session)
        assert len(list_transactions(
            session, description_query="pyaterochka",
        )) == 1

    def test_search_matches_description_or_counterparty(self, session):
        """Подстрока находится и в description, и в counterparty_name — OR."""
        self._seed(session)
        assert len(list_transactions(session, description_query="PYATERO")) == 1

    def test_search_empty_query_no_filter(self, session):
        self._seed(session)
        assert len(list_transactions(session, description_query="")) == 3
        assert len(list_transactions(session, description_query="   ")) == 3

    def test_search_no_match(self, session):
        self._seed(session)
        assert list_transactions(
            session, description_query="нет-такого-слова",
        ) == []
        assert count_transactions(
            session, description_query="нет-такого-слова",
        ) == 0

    def test_count_consistent_with_list(self, session):
        """count_transactions учитывает description_query — пагинация не врёт."""
        self._seed(session)
        q = "COFFEE"
        assert (
            count_transactions(session, description_query=q)
            == len(list_transactions(session, description_query=q))
        )

    def test_search_combined_with_other_filters(self, session):
        self._seed(session)
        rows = list_transactions(
            session,
            description_query="я",   # есть в "Пятёрочка" и "Кофейня"
            date_from=date(2024, 1, 10),
            date_to=date(2024, 1, 16),
        )
        assert len(rows) == 2

    def test_search_with_pagination(self, session):
        for i in range(5):
            add_manual_transaction(
                session, account_id=1, date=date(2024, 1, 1 + i),
                amount=-(i + 1) * 100, description=f"Кофейня #{i}",
            )
        add_manual_transaction(
            session, account_id=1, date=date(2024, 2, 1),
            amount=-999, description="Пятёрочка",
        )
        q = "Кофейня"
        assert count_transactions(session, description_query=q) == 5
        page1 = list_transactions(
            session, description_query=q, limit=2, offset=0,
        )
        page2 = list_transactions(
            session, description_query=q, limit=2, offset=2,
        )
        assert len(page1) == 2
        assert len(page2) == 2
        assert {t.transaction_id for t in page1}.isdisjoint(
            {t.transaction_id for t in page2}
        )