"""SQLAlchemy-модели v1 (SQLAlchemy 2.x, declarative Mapped/mapped_column).

Только декларации. Импорт, дедупликация, вычисление transaction_hash - вне этого модуля.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.db.constants import (
    ACCOUNT_CURRENCIES,
    CATEGORY_TYPES,
    CURRENT_HASH_VERSION,
    IS_TRANSFER_VALUES,
    MIN_HASH_VERSION,
    SOURCES,
    TRANSACTION_CURRENCIES,
    sql_in_list,
)


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    account_number_masked: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)

    fio: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    card_number_masked: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    open_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    statements: Mapped[list["Statement"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "bank_name",
            "account_number_masked",
            name="uq_accounts_bank_number",
        ),
        CheckConstraint(
            f"currency IN {sql_in_list(ACCOUNT_CURRENCIES)}",
            name="ck_accounts_currency",
        ),
        CheckConstraint(
            "open_date IS NULL OR close_date IS NULL OR open_date <= close_date",
            name="ck_accounts_dates_order",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Account(account_id={self.account_id}, "
            f"bank_name={self.bank_name!r}, "
            f"account_name={self.account_name!r}, "
            f"currency={self.currency!r})"
        )

    def business_key(self) -> str:
        """Стабильный бизнес-ключ для хэширования транзакций.

        Использование:
            prepare_statement(..., account_key=account.business_key())
            add_manual_transaction(..., account_key=account.business_key())

        В отличие от str(account_id), не меняется при пересоздании БД.
        Формат совпадает с тем, что уже упоминается в README как "bank:sber:****1234".
        """
        return f"bank:{self.bank_name}:{self.account_number_masked}"


class Statement(TimestampMixin, Base):
    __tablename__ = "statements"

    statement_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    account: Mapped["Account"] = relationship(back_populates="statements")

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="statement",
        cascade="save-update, merge",
        passive_deletes="all",
    )

    __table_args__ = (
        Index("ix_statements_account_id", "account_id"),
        CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
            name="ck_statements_period_order",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Statement(statement_id={self.statement_id}, "
            f"account_id={self.account_id}, "
            f"file_name={self.file_name!r}, "
            f"period={self.period_start}..{self.period_end})"
        )


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    parent_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True
    )

    parent: Mapped[Optional["Category"]] = relationship(
        back_populates="children",
        remote_side="Category.category_id",
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent",
        passive_deletes=True,
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="category",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("name", "parent_category_id", name="uq_categories_name_parent"),
        Index(
            "uq_categories_name_root",
            "name",
            unique=True,
            sqlite_where=text("parent_category_id IS NULL"),
        ),
        CheckConstraint(
            f"type IN {sql_in_list(CATEGORY_TYPES)}",
            name="ck_categories_type",
        ),
        Index("ix_categories_parent_category_id", "parent_category_id"),
    )

    def __repr__(self) -> str:
        return (
            f"Category(category_id={self.category_id}, "
            f"name={self.name!r}, type={self.type!r}, "
            f"parent_category_id={self.parent_category_id})"
        )


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False
    )
    statement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("statements.statement_id", ondelete="SET NULL"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True
    )
    authorization_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_transfer: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    transaction_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CURRENT_HASH_VERSION,
        server_default=str(CURRENT_HASH_VERSION),
    )
    source: Mapped[str] = mapped_column(String, nullable=False)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    statement: Mapped[Optional["Statement"]] = relationship(back_populates="transactions")
    category: Mapped[Optional["Category"]] = relationship(back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("account_id", "transaction_hash", name="uq_transactions_account_hash"),
        CheckConstraint(
            f"currency IN {sql_in_list(TRANSACTION_CURRENCIES)}",
            name="ck_transactions_currency",
        ),
        CheckConstraint(
            f"source IN {sql_in_list(SOURCES)}",
            name="ck_transactions_source",
        ),
        CheckConstraint(
            f"is_transfer IN {sql_in_list(IS_TRANSFER_VALUES)}",
            name="ck_transactions_is_transfer",
        ),
        CheckConstraint(
            f"hash_version >= {MIN_HASH_VERSION}",
            name="ck_transactions_hash_version",
        ),
        Index("ix_transactions_date", "date"),
        Index("ix_transactions_account_date", "account_id", "date"),
        Index("ix_transactions_statement_id", "statement_id"),
        Index("ix_transactions_category_id", "category_id"),
    )

    def __repr__(self) -> str:
        desc = (self.description or "")[:30]
        return (
            f"Transaction(transaction_id={self.transaction_id}, "
            f"account_id={self.account_id}, "
            f"statement_id={self.statement_id}, "
            f"date={self.date}, amount={self.amount}, "
            f"description={desc!r})"
        )