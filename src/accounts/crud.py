"""CRUD аккаунтов.

`find_or_create_account` - в `src.accounts.find_or_create`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src._internal.sentinel import UNSET, _UnsetType
from src.db import Account, Statement, Transaction


@dataclass(frozen=True, slots=True)
class DeleteAccountResult:
    account_id: int
    deleted_statements: int
    deleted_transactions: int


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_account(session: Session, account_id: int) -> Account | None:
    """None если не найден."""
    return session.get(Account, account_id)


def list_accounts(session: Session) -> list[Account]:
    """Все аккаунты. Сортировка: bank_name, account_name, account_id ASC."""
    return list(
        session.execute(
            select(Account).order_by(
                Account.bank_name.asc(),
                Account.account_name.asc(),
                Account.account_id.asc(),
            )
        ).scalars().all()
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_account(
    session: Session,
    *,
    bank_name: str,
    account_name: str,
    account_number_masked: str,
    currency: str = "RUB",
    fio: str | None = None,
    card_number_masked: str | None = None,
    open_date: date | None = None,
    close_date: date | None = None,
) -> Account:
    """Создать аккаунт.
    rgs:
        currency: одна из ACCOUNT_CURRENCIES = ("RUB", "USD", "EUR", "MULTI").
            Дефолт "RUB" - для обычного рублёвого счёта.
            Для мультивалютного счёта caller ДОЛЖЕН передать currency="MULTI" явно;
            дефолт "RUB" не превратится в "MULTI" автоматически.

    Raises:
        ValueError: пустые bank_name / account_name /
                    account_number_masked; currency не в ACCOUNT_CURRENCIES;
                    пара (bank_name, account_number_masked) уже существует;
                    open_date > close_date.
    """
    bank_name = (bank_name or "").strip()
    account_name = (account_name or "").strip()
    account_number_masked = (account_number_masked or "").strip()
    currency = (currency or "").strip().upper()

    if not bank_name:
        raise ValueError("bank_name must be non-empty")
    if not account_name:
        raise ValueError("account_name must be non-empty")
    if not account_number_masked:
        raise ValueError("account_number_masked must be non-empty")
    if not currency:
        raise ValueError("currency must be non-empty")

    existing_id = session.execute(
        select(Account.account_id).where(
            Account.bank_name == bank_name,
            Account.account_number_masked == account_number_masked,
        )
    ).scalar_one_or_none()
    if existing_id is not None:
        raise ValueError(
            f"account with bank_name={bank_name!r} and "
            f"account_number_masked={account_number_masked!r} "
            f"already exists (id={existing_id})"
        )

    # Pre-check CHECK(open_date <= close_date).
    if open_date is not None and close_date is not None and open_date > close_date:
        raise ValueError(
            f"open_date ({open_date}) must be <= close_date ({close_date})"
        )

    account = Account(
        bank_name=bank_name,
        account_name=account_name,
        account_number_masked=account_number_masked,
        currency=currency,
        fio=(fio.strip() if fio else None),
        card_number_masked=(
            card_number_masked.strip() if card_number_masked else None
        ),
        open_date=open_date,
        close_date=close_date,
    )
    session.add(account)
    session.flush()
    return account


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_account(
    session: Session,
    account_id: int,
    *,
    bank_name: str | _UnsetType = UNSET,
    account_name: str | _UnsetType = UNSET,
    account_number_masked: str | _UnsetType = UNSET,
    currency: str | _UnsetType = UNSET,
    fio: str | None | _UnsetType = UNSET,
    card_number_masked: str | None | _UnsetType = UNSET,
    open_date: date | None | _UnsetType = UNSET,
    close_date: date | None | _UnsetType = UNSET,
) -> Account:
    """..."""
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"account with id={account_id} not found")   # ← ПЕРВЫМ

    # --- pre-check UNIQUE(bank_name, account_number_masked) ---
    # Считаем «итоговые» значения: переданное (нормализованное) или текущее.
    final_bank = (
        (bank_name or "").strip()
        if isinstance(bank_name, str)
        else account.bank_name
    )
    final_number = (
        (account_number_masked or "").strip()
        if isinstance(account_number_masked, str)
        else account.account_number_masked
    )

    pair_changed = (final_bank, final_number) != (
        account.bank_name, account.account_number_masked,
    )
    pair_valid = bool(final_bank) and bool(final_number)

    if pair_changed and pair_valid:
        existing_id = session.execute(
            select(Account.account_id).where(
                Account.bank_name == final_bank,
                Account.account_number_masked == final_number,
                Account.account_id != account_id,
            )
        ).scalar_one_or_none()
        if existing_id is not None:
            raise ValueError(
                f"account with bank_name={final_bank!r} and "
                f"account_number_masked={final_number!r} "
                f"already exists (id={existing_id})"
            )

    # --- pre-check CHECK(open_date <= close_date) ---
    final_open = (
        open_date if not isinstance(open_date, _UnsetType) else account.open_date
    )
    final_close = (
        close_date if not isinstance(close_date, _UnsetType) else account.close_date
    )
    if (
        final_open is not None
        and final_close is not None
        and final_open > final_close
    ):
        raise ValueError(
            f"open_date ({final_open}) must be <= close_date ({final_close})"
        )

    if not isinstance(bank_name, _UnsetType):
        bank_name = (bank_name or "").strip()
        if not bank_name:
            raise ValueError("bank_name must be non-empty")
        account.bank_name = bank_name

    if not isinstance(account_name, _UnsetType):
        account_name = (account_name or "").strip()
        if not account_name:
            raise ValueError("account_name must be non-empty")
        account.account_name = account_name

    if not isinstance(account_number_masked, _UnsetType):
        account_number_masked = (account_number_masked or "").strip()
        if not account_number_masked:
            raise ValueError("account_number_masked must be non-empty")
        account.account_number_masked = account_number_masked

    if not isinstance(currency, _UnsetType):
        new_currency = (currency or "").strip().upper()
        if not new_currency:
            raise ValueError("currency must be non-empty")
        if new_currency != account.currency and new_currency != "MULTI":
            conflicting = session.execute(
                select(func.count(Transaction.transaction_id)).where(
                    Transaction.account_id == account_id,
                    Transaction.currency != new_currency,
                )
            ).scalar_one()
            if conflicting:
                raise ValueError(
                    f"cannot change currency to {new_currency!r}: account has "
                    f"{conflicting} transaction(s) in another currency. "
                    f"Change to 'MULTI' or reassign/delete those transactions."
                )
        account.currency = new_currency

    if not isinstance(fio, _UnsetType):
        account.fio = (fio.strip() if fio else None)

    if not isinstance(card_number_masked, _UnsetType):
        account.card_number_masked = (
            card_number_masked.strip() if card_number_masked else None
        )

    if not isinstance(open_date, _UnsetType):
        account.open_date = open_date

    if not isinstance(close_date, _UnsetType):
        account.close_date = close_date

    session.flush()
    return account


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_account(
    session: Session,
    account_id: int,
    *,
    cascade: bool = False,
) -> DeleteAccountResult:
    """Удалить аккаунт.

    cascade=False (default):
        ValueError, если у аккаунта есть statements или transactions.

    cascade=True:
        Удаляются аккаунт, все его statements и все его transactions.

    Raises:
        ValueError: аккаунт не найден; или cascade=False при наличии данных.
    """
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"account with id={account_id} not found")

    statements_count = session.execute(
        select(func.count(Statement.statement_id)).where(
            Statement.account_id == account_id
        )
    ).scalar_one()
    transactions_count = session.execute(
        select(func.count(Transaction.transaction_id)).where(
            Transaction.account_id == account_id
        )
    ).scalar_one()

    if not cascade and (statements_count or transactions_count):
        raise ValueError(
            f"account with id={account_id} has "
            f"{statements_count} statement(s) and "
            f"{transactions_count} transaction(s); pass cascade=True to delete"
        )

    if cascade:
        deleted_tx = 0
        deleted_stmt = 0
        if transactions_count:
            result = session.execute(
                delete(Transaction).where(
                    Transaction.account_id == account_id
                ),
                execution_options={"synchronize_session": False},
            )
            deleted_tx = result.rowcount or 0
        if statements_count:
            result = session.execute(
                delete(Statement).where(
                    Statement.account_id == account_id
                ),
                execution_options={"synchronize_session": False},
            )
            deleted_stmt = result.rowcount or 0
    else:
        deleted_tx = 0
        deleted_stmt = 0

    session.delete(account)
    session.flush()
    return DeleteAccountResult(
        account_id=account_id,
        deleted_statements=statements_count,
        deleted_transactions=transactions_count,
    )