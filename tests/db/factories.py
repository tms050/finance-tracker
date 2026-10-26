# tests/db/factories.py
from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from src.db.models import Account, Category, Statement, Transaction


def make_account(
    session: Session,
    *,
    currency: str = "RUB",
    bank_name: str = "Sber",
    account_number_masked: str = "****0000",
    flush: bool = True,
    **overrides,
) -> Account:
    account = Account(
        bank_name=bank_name,
        account_name="Main",
        account_number_masked=account_number_masked,
        currency=currency,
        **overrides,
    )
    session.add(account)
    if flush:
        session.flush()
    return account


def make_statement(
    session: Session,
    account: Account,
    *,
    file_hash: str | None = None,
    file_name: str = "statement.pdf",
    flush: bool = True,
    **overrides,
) -> Statement:
    statement = Statement(
        account_id=account.account_id,
        file_name=file_name,
        file_hash=file_hash or uuid4().hex,
        **overrides,
    )
    session.add(statement)
    if flush:
        session.flush()
    return statement


def make_category(
    session: Session,
    *,
    name: str = "Food",
    type: str = "expense",
    parent_category_id: int | None = None,
    flush: bool = True,
    **overrides,
) -> Category:
    category = Category(
        name=name,
        type=type,
        parent_category_id=parent_category_id,
        **overrides,
    )
    session.add(category)
    if flush:
        session.flush()
    return category


def make_transaction(
    session: Session,
    account: Account,
    *,
    statement: Statement | None = None,
    transaction_hash: str | None = None,
    flush: bool = True,
    **overrides,
) -> Transaction:
    defaults: dict = dict(
        account_id=account.account_id,
        statement_id=statement.statement_id if statement else None,
        date=date(2026, 1, 1),
        time=None,
        amount=-10_000,
        currency=(
            account.currency if account.currency in ("RUB", "USD", "EUR") else "RUB"
        ),
        description="Test transaction",
        counterparty_name=None,
        category_id=None,
        authorization_code=None,
        raw_category=None,
        is_transfer=0,
        transaction_hash=transaction_hash or uuid4().hex,
        hash_version=1,
        source="pdf",
    )
    defaults.update(overrides)
    transaction = Transaction(**defaults)
    session.add(transaction)
    if flush:
        session.flush()
    return transaction