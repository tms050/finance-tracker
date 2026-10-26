"""FK-каскады: ON DELETE CASCADE и ON DELETE SET NULL."""

from __future__ import annotations

from sqlalchemy import select

from src.db.models import Category, Statement, Transaction
from tests.db.factories import (
    make_account,
    make_category,
    make_statement,
    make_transaction,
)
from src.statements import delete_statement

def test_delete_category_sets_transaction_category_id_to_null(session):
    account = make_account(session)
    category = make_category(session)
    transaction = make_transaction(session, account, category_id=category.category_id)
    tx_id = transaction.transaction_id
    session.commit()

    session.delete(category)
    session.commit()
    session.expire_all()

    refreshed = session.get(Transaction, tx_id)
    assert refreshed is not None
    assert refreshed.category_id is None


def test_delete_parent_category_sets_child_parent_id_to_null(session):
    parent = make_category(session, name="Food")
    child = make_category(session, name="Snacks", parent_category_id=parent.category_id)
    child_id = child.category_id
    session.commit()

    session.delete(parent)
    session.commit()
    session.expire_all()

    refreshed = session.get(Category, child_id)
    assert refreshed is not None
    assert refreshed.parent_category_id is None


def test_delete_account_cascades_statements_and_transactions(session):
    account = make_account(session)
    statement = make_statement(session, account)
    make_transaction(session, account, statement=statement)
    make_transaction(session, account, statement=None)
    session.commit()

    session.delete(account)
    session.commit()
    session.expire_all()

    assert session.scalars(select(Statement)).all() == []
    assert session.scalars(select(Transaction)).all() == []




def test_delete_statement_with_orm_cascade_deletes_transactions(session):
    """Явный каскад через CRUD (delete_statement(cascade_transactions=True))."""

    account = make_account(session)
    st1 = make_statement(session, account, file_name="a.pdf")
    st2 = make_statement(session, account, file_name="b.pdf")
    tx1 = make_transaction(session, account, statement=st1)
    tx2 = make_transaction(session, account, statement=st2)
    tx_manual = make_transaction(session, account, statement=None)
    tx1_id, tx2_id, manual_id = (
        tx1.transaction_id, tx2.transaction_id, tx_manual.transaction_id
    )
    session.commit()

    delete_statement(session, st1.statement_id, cascade_transactions=True)
    session.commit()

    remaining = {t.transaction_id for t in session.scalars(select(Transaction)).all()}
    assert tx1_id not in remaining   # удалён
    assert tx2_id in remaining       # другой statement не тронут
    assert manual_id in remaining


def test_delete_statement_via_fk_sets_null(session):
    """Голый session.delete(stmt) — FK ON DELETE SET NULL обнуляет statement_id."""
    account = make_account(session)
    st1 = make_statement(session, account, file_name="a.pdf")
    st2 = make_statement(session, account, file_name="b.pdf")
    tx1 = make_transaction(session, account, statement=st1)
    tx2 = make_transaction(session, account, statement=st2)
    tx_manual = make_transaction(session, account, statement=None)
    tx1_id, tx2_id, manual_id = (
        tx1.transaction_id, tx2.transaction_id, tx_manual.transaction_id
    )
    session.commit()

    session.delete(st1)
    session.commit()
    session.expire_all()
    
    refreshed = session.get(Transaction, tx1_id)
    remaining = {t.transaction_id for t in session.scalars(select(Transaction)).all()}
    assert refreshed is not None
    assert refreshed.statement_id is None   # НЕ удалён, а отвязан
    assert refreshed.account_id == account.account_id
    assert tx2_id in remaining
    assert manual_id in remaining