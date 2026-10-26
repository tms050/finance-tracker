"""B2d: найти или создать аккаунт по бизнес-ключу.

Бизнес-ключ - (bank_name, account_number_masked), exact match, case-sensitive.
Вызывается UI-слоем ДО prepare_statement, если пользователь не выбрал счёт.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.accounts.crud import create_account
from src.db import Account


def find_or_create_account(
    session: Session,
    *,
    bank_name: str,
    account_number_masked: str,
    account_name: str = "",
    currency: str = "RUB",
    fio: str | None = None,
    card_number_masked: str | None = None,
    open_date: date | None = None,
    close_date: date | None = None,
) -> tuple[Account, bool, list[str]]:
    """Найти по (bank_name, account_number_masked) или создать.

    Returns:
        (account, created, warnings)
        - created=True если создан; False если найден.
        - warnings: непусто, если у найденного аккаунта расходятся
          переданные (не-None) атрибуты. Существующий аккаунт не обновляется.

    Raises:
        ValueError: пустые bank_name / account_number_masked.
    """
    bank_name = (bank_name or "").strip()
    account_number_masked = (account_number_masked or "").strip()
    if not bank_name:
        raise ValueError("bank_name must be non-empty")
    if not account_number_masked:
        raise ValueError("account_number_masked must be non-empty")

    existing = session.execute(
        select(Account).where(
            Account.bank_name == bank_name,
            Account.account_number_masked == account_number_masked,
        )
    ).scalar_one_or_none()

    if existing is not None:
        warnings: list[str] = []

        if currency and currency.upper() != existing.currency:
            warnings.append(
                f"У счёта {bank_name} {account_number_masked} валюта "
                f"'{existing.currency}', а передана '{currency.upper()}'. "
                f"Существующий счёт использован как есть; проверьте, что это "
                f"тот самый счёт."
            )

        if fio is not None and existing.fio != fio.strip():
            warnings.append(
                f"У счёта {bank_name} {account_number_masked} ФИО "
                f"'{existing.fio}', а передано '{fio.strip()}'."
            )

        if (
            card_number_masked is not None
            and existing.card_number_masked != card_number_masked.strip()
        ):
            warnings.append(
                f"У счёта {bank_name} {account_number_masked} номер карты "
                f"'{existing.card_number_masked}', а передан "
                f"'{card_number_masked.strip()}'."
            )

        if open_date is not None and existing.open_date != open_date:
            warnings.append(
                f"У счёта {bank_name} {account_number_masked} дата открытия "
                f"{existing.open_date}, а передана {open_date}."
            )

        if close_date is not None and existing.close_date != close_date:
            warnings.append(
                f"У счёта {bank_name} {account_number_masked} дата закрытия "
                f"{existing.close_date}, а передана {close_date}."
            )

        return existing, False, warnings

    account = create_account(
        session,
        bank_name=bank_name,
        account_name=account_name.strip() if account_name else bank_name,
        account_number_masked=account_number_masked,
        currency=currency,
        fio=fio,
        card_number_masked=card_number_masked,
        open_date=open_date,
        close_date=close_date,
    )
    return account, True, []