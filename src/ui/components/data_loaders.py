"""Загрузка данных для UI. Только SQLAlchemy + чистые форматтеры."""
from __future__ import annotations

from typing import Any

import streamlit as st

from src.accounts import list_accounts
from src.categories import list_categories
from src.db import get_session
from src.transactions import count_transactions, list_transactions
from src.ui.formatters import build_category_labels


# ---------------------------------------------------------------------------
# Кэшированные загрузчики (TTL - «страховка», основная инвалидация - .clear())
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def load_accounts_cached() -> list[dict]:
    """Все счета как plain-dict. Инвалидируется load_accounts_cached.clear()."""
    with get_session() as session:
        return [
            {
                "account_id": a.account_id,
                "bank_name": a.bank_name,
                "account_name": a.account_name,
                "account_number_masked": a.account_number_masked,
                "currency": a.currency,
                "fio": a.fio,
                "card_number_masked": a.card_number_masked,
                "open_date": a.open_date,
                "close_date": a.close_date,
                "is_closed": a.close_date is not None,
            }
            for a in list_accounts(session)
        ]


@st.cache_data(ttl=60, show_spinner=False)
def load_category_labels() -> dict[int, str]:
    """{category_id: display_name}. Инвалидируется load_category_labels.clear()."""
    with get_session() as session:
        return build_category_labels(list_categories(session))


@st.cache_data(ttl=15, show_spinner=False)
def load_transactions(
    filters: dict,
    *,
    page: int = 0,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, dict[int, str]]:
    """Загрузить транзакции как plain-dict. Кэш на 15с - короче, чтобы
    после add/assign в другой вкладке не было рассинхрона."""
    with get_session() as session:
        total = count_transactions(session, **filters)
        kwargs: dict[str, Any] = {}
        if page_size is not None:
            kwargs["limit"] = page_size
            kwargs["offset"] = page * page_size
        txs = list_transactions(session, **filters, **kwargs)
        cat_labels = build_category_labels(list_categories(session))
        rows: list[dict[str, Any]] = [
            {
                "transaction_id": tx.transaction_id,
                "date": tx.date,
                "time": tx.time,
                "amount": tx.amount,
                "currency": tx.currency,
                "category_id": tx.category_id,
                "raw_category": tx.raw_category,
                "counterparty_name": tx.counterparty_name,
                "description": tx.description,
                "is_transfer": bool(tx.is_transfer),
            }
            for tx in txs
        ]
    return rows, total, cat_labels


# ---------------------------------------------------------------------------
# Инвалидация - вызывать в местах, где вы делаете st.rerun()
# ---------------------------------------------------------------------------

def invalidate_accounts() -> None:
    load_accounts_cached.clear()


def invalidate_categories() -> None:
    load_category_labels.clear()


def invalidate_transactions() -> None:
    load_transactions.clear()


def invalidate_all() -> None:
    """Сброс всех кэшей - для кнопки «Обновить» в сайдбаре."""
    st.cache_data.clear()