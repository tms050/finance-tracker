"""UI-6: управление счетами (список, создание, удаление)."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st

from src.accounts import create_account, delete_account, list_accounts
from src.db import get_session
from src.db.constants import ACCOUNT_CURRENCIES
from src.ui.components.data_loaders import (
    invalidate_accounts,
    invalidate_transactions,
)
from src.ui.formatters import format_date, format_optional_text

_CURRENCIES = list(ACCOUNT_CURRENCIES)  # ("RUB", "USD", "EUR", "MULTI")


def render() -> None:
    if "acc_flash" in st.session_state:
        st.success(st.session_state.pop("acc_flash"))

    st.markdown("## Счета")
    accounts = _load_accounts_dto()

    if accounts:
        _render_catalog(accounts)
    else:
        st.info(
            "Счетов пока нет - создайте первый ниже. После этого станут "
            "доступны остальные разделы: загрузка выписки, добавление "
            "транзакций, статистика, категории."
        )

    st.divider()
    st.markdown("### Создать счёт")
    _render_create_form()


# ---------------------------------------------------------------------------
# Загрузка (DTO - ORM не выходит за пределы with get_session())
# ---------------------------------------------------------------------------

def _load_accounts_dto() -> list[SimpleNamespace]:
    with get_session() as session:
        return [
            SimpleNamespace(
                account_id=a.account_id,
                bank_name=a.bank_name,
                account_name=a.account_name,
                account_number_masked=a.account_number_masked,
                currency=a.currency,
                fio=a.fio,
                card_number_masked=a.card_number_masked,
                open_date=a.open_date,
                close_date=a.close_date,
            )
            for a in list_accounts(session)
        ]


# ---------------------------------------------------------------------------
# Список + удаление
# ---------------------------------------------------------------------------

def _render_catalog(accounts: list[SimpleNamespace]) -> None:
    rows = [
        {
            "Банк": a.bank_name,
            "Название": a.account_name,
            "Номер": a.account_number_masked,
            "Валюта": a.currency,
            "ФИО": format_optional_text(a.fio),
            "Карта": format_optional_text(a.card_number_masked),
            "Открыт": format_date(a.open_date),
            "Закрыт": format_date(a.close_date),
        }
        for a in accounts
    ]
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Банк": st.column_config.TextColumn("Банк", width="medium"),
            "Название": st.column_config.TextColumn("Название", width="medium"),
            "Номер": st.column_config.TextColumn("Номер", width="small"),
            "Валюта": st.column_config.TextColumn("Валюта", width="small"),
            "ФИО": st.column_config.TextColumn("ФИО", width="medium"),
            "Карта": st.column_config.TextColumn("Карта", width="small"),
            "Открыт": st.column_config.TextColumn("Открыт", width="small"),
            "Закрыт": st.column_config.TextColumn("Закрыт", width="small"),
        },
    )

    st.divider()
    st.markdown("### Удалить счёт")
    _render_delete_section(accounts)


def _render_delete_section(accounts: list[SimpleNamespace]) -> None:
    labels = {
        a.account_id: (
            f"{a.bank_name} · {a.account_name} · {a.account_number_masked} "
            f"({a.currency})"
        )
        for a in accounts
    }
    options = list(labels)

    acc_id = st.selectbox(
        "Счёт для удаления",
        options=options,
        format_func=lambda x: labels[x],
        key="acc_delete_id",
    )

    # Двухшаговое подтверждение.
    confirm_key = f"acc_confirm_delete_{acc_id}"
    if not st.session_state.get(confirm_key):
        if st.button(
            "Удалить счёт",
            icon=":material/delete:",
            type="secondary",
            key=f"acc_delete_btn_{acc_id}",
        ):
            st.session_state[confirm_key] = True
            st.rerun()
        return

    st.warning(
        f"Удалить счёт **{labels[acc_id]}**?\n\n"
        f"Это необратимо: все выписки и транзакции этого счёта будут "
        f"удалены вместе со счётом."
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button(
            "Да, удалить",
            type="primary",
            key=f"acc_confirm_yes_{acc_id}",
            use_container_width=True,
        ):
            _do_delete(acc_id, confirm_key)
    with col_no:
        if st.button(
            "Отмена",
            key=f"acc_confirm_no_{acc_id}",
            use_container_width=True,
        ):
            st.session_state.pop(confirm_key, None)
            st.rerun()


def _do_delete(acc_id: int, confirm_key: str) -> None:
    try:
        with st.spinner("Удаление счёта…"):
            with get_session() as session:
                result = delete_account(session, acc_id, cascade=True)
    except Exception as e:
        st.error(f"Ошибка удаления: {type(e).__name__}: {e}")
        return

    # Каскад удаляет и транзакции - сбрасываем оба кэша.
    invalidate_accounts()
    invalidate_transactions()

    st.session_state.pop(confirm_key, None)
    st.session_state["acc_flash"] = (
        f"Счёт удалён: statements={result.deleted_statements}, "
        f"transactions={result.deleted_transactions}."
    )
    st.rerun()


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------

def _render_create_form() -> None:
    with st.form("account_create_form", clear_on_submit=True):
        bank_name = st.text_input(
            "Банк *", key="acc_create_bank",
            placeholder="Сбербанк, Т-Банк, ...",
        )
        account_name = st.text_input(
            "Название счёта *", key="acc_create_name",
            placeholder="Основной, Зарплатный, ...",
        )
        number = st.text_input(
            "Номер счёта (маскированный) *", key="acc_create_number",
            placeholder="**** 1234",
        )
        currency = st.selectbox(
            "Валюта *",
            options=_CURRENCIES,
            key="acc_create_currency",
            help=(
                "MULTI - для мультивалютного счёта. При ручном добавлении "
                "транзакции валюта будет спрашиваться явно."
            ),
        )

        with st.expander("Дополнительно (необязательно)"):
            fio = st.text_input("ФИО", key="acc_create_fio")
            card = st.text_input(
                "Номер карты (маскированный)", key="acc_create_card",
            )
            col1, col2 = st.columns(2)
            with col1:
                open_date = st.date_input(
                    "Дата открытия", value=None, key="acc_create_open",
                ) or None
            with col2:
                close_date = st.date_input(
                    "Дата закрытия", value=None, key="acc_create_close",
                ) or None

        submitted = st.form_submit_button("Создать", type="primary")

    if not submitted:
        return

    # Валидация до бэкенда - мгновенная обратная связь.
    if not bank_name.strip():
        st.error("Банк не может быть пустым.")
        return
    if not account_name.strip():
        st.error("Название счёта не может быть пустым.")
        return
    if not number.strip():
        st.error("Номер счёта не может быть пустым.")
        return
    if open_date and close_date and open_date > close_date:
        st.error("Дата открытия не может быть позже даты закрытия.")
        return

    try:
        with st.spinner("Создание счёта…"):
            with get_session() as session:
                acc = create_account(
                    session,
                    bank_name=bank_name,
                    account_name=account_name,
                    account_number_masked=number,
                    currency=currency,
                    fio=fio or None,
                    card_number_masked=card or None,
                    open_date=open_date,
                    close_date=close_date,
                )
                acc_id = acc.account_id
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка создания: {type(e).__name__}: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return

    invalidate_accounts()
    st.session_state["acc_flash"] = f"Счёт создан (id={acc_id})."
    st.rerun()