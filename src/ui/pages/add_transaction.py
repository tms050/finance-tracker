"""UI-5: ручное добавление транзакции."""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

import streamlit as st

from src.accounts import list_accounts
from src.categories import list_categories
from src.db import get_session
from src.transactions import DuplicateTransactionError, add_manual_transaction
from src.ui.components.data_loaders import invalidate_transactions
from src.ui.formatters import (
    EMPTY,
    build_category_labels,
    format_account_label,
    format_amount,
    format_amount_input_to_kopecks,
    format_date,
)

_CURRENCIES = ["RUB", "USD", "EUR"]
_LARGE_AMOUNT_RUB = 100_000

_FORM_STATE_KEYS = (
    "add_tx_amount",
    "add_tx_description",
    "add_tx_counterparty",
    "add_tx_category",
    "add_tx_is_transfer",
    "add_tx_date",
    "add_tx_time",
    "add_tx_use_time",
    "add_tx_type",
    "add_tx_currency",
)


def render(account_id: int | None) -> None:
    if "add_tx_flash" in st.session_state:
        st.success(st.session_state.pop("add_tx_flash"))

    st.markdown("## Добавить транзакцию")
    st.caption(
        "Транзакция сохраняется с `source='manual'`. После добавления видна "
        "во вкладке «Транзакции» и учитывается в «Статистике»."
    )

    accounts = _load_accounts()
    if not accounts:
        st.info(
            "Сначала создайте счёт - во вкладке «Счета» или загрузите "
            "выписку во вкладке «Загрузка»."
        )
        return

    categories = _load_categories_dto()
    if not categories:
        st.info(
            "В справочнике пока нет категорий. Можно добавить без категории "
            "или создать категорию во вкладке «Категории»."
        )

    cat_labels = build_category_labels(categories)
    _render_form(accounts, categories, cat_labels, account_id)


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------

def _load_accounts() -> list[dict]:
    with get_session() as session:
        return [
            {
                "account_id": a.account_id,
                "bank_name": a.bank_name,
                "account_name": a.account_name,
                "account_number_masked": a.account_number_masked,
                "currency": a.currency,
                "is_closed": a.close_date is not None,
                "business_key": a.business_key(),
            }
            for a in list_accounts(session)
        ]


def _load_categories_dto() -> list[SimpleNamespace]:
    with get_session() as session:
        return [
            SimpleNamespace(
                category_id=c.category_id,
                name=c.name,
                type=c.type,
                parent_category_id=c.parent_category_id,
            )
            for c in list_categories(session)
        ]


def _clear_form_state() -> None:
    for k in _FORM_STATE_KEYS:
        st.session_state.pop(k, None)


# ---------------------------------------------------------------------------
# Форма
# ---------------------------------------------------------------------------

def _render_form(
    accounts: list[dict],
    categories,
    cat_labels: dict[int, str],
    preselected_account_id: int | None,
) -> None:
    acc_by_id = {a["account_id"]: a for a in accounts}
    account_options = list(acc_by_id)

    default_acc_id = (
        preselected_account_id
        if preselected_account_id in acc_by_id
        else account_options[0]
    )

    def _fmt_acc(aid: int) -> str:
        a = acc_by_id[aid]
        return format_account_label(
            a["bank_name"], a["account_name"],
            a["account_number_masked"], is_closed=a["is_closed"],
        )

    cat_options: list[int | None] = [None] + [c.category_id for c in categories]

    def _fmt_cat(cid: int | None) -> str:
        if cid is None:
            return "- Без категории"
        return cat_labels.get(cid, f"#{cid}")

    st.markdown("**Дата и время**")
    use_time = st.checkbox(
        "Указать время", value=False, key="add_tx_use_time",
    )

    # Кнопка «Очистить» - вне st.form, чтобы работать без сабмита.
    if st.button(
        "Очистить форму",
        icon=":material/clear:",
        key="add_tx_clear",
    ):
        _clear_form_state()
        st.rerun()

    with st.form("add_tx_form"):
        acc_id = st.selectbox(
            "Счёт", options=account_options,
            index=account_options.index(default_acc_id),
            format_func=_fmt_acc, key="add_tx_account",
        )
        acc = acc_by_id[acc_id]

        if use_time:
            col_date, col_time = st.columns(2)
            with col_date:
                tx_date = st.date_input(
                    "Дата", value=date.today(), key="add_tx_date",
                )
            with col_time:
                tx_time = st.time_input(
                    "Время", value=time(12, 0), key="add_tx_time",
                )
        else:
            tx_date = st.date_input(
                "Дата", value=date.today(), key="add_tx_date",
            )
            tx_time = None

        col_type, col_amount = st.columns([1, 2])
        with col_type:
            tx_type = st.radio(
                "Тип", options=["Расход", "Доход"],
                horizontal=True, key="add_tx_type",
            )
        with col_amount:
            amount_rub = st.number_input(
                "Сумма, ₽", min_value=0.01, value=None,
                step=0.01, format="%.2f", key="add_tx_amount",
            )

        if amount_rub is not None and amount_rub >= _LARGE_AMOUNT_RUB:
            st.warning(
                f"Большая сумма: {amount_rub:,.2f} ₽. Проверьте, что "
                f"ввели правильное значение."
            )

        if acc["currency"] == "MULTI":
            currency = st.selectbox(
                "Валюта", options=_CURRENCIES, key="add_tx_currency",
            )
        else:
            st.caption(f"Валюта: **{acc['currency']}** (определена счётом)")
            currency = None

        category_id = st.selectbox(
            "Категория", options=cat_options,
            format_func=_fmt_cat, key="add_tx_category",
        )

        counterparty = st.text_input(
            "Контрагент (необязательно)", key="add_tx_counterparty",
        )
        description = st.text_area(
            "Описание (необязательно)", key="add_tx_description",
        )
        is_transfer = st.checkbox(
            "Это перевод между своими счетами",
            value=False, key="add_tx_is_transfer",
        )

        submitted = st.form_submit_button("Добавить", type="primary")

    if not submitted:
        return

    _handle_submit(
        acc_id=acc_id,
        account_key=acc["business_key"],
        tx_date=tx_date,
        tx_time=tx_time,
        tx_type=tx_type,
        amount_rub=amount_rub,
        currency=currency,
        category_id=category_id,
        counterparty=counterparty,
        description=description,
        is_transfer=is_transfer,
    )


# ---------------------------------------------------------------------------
# Сабмит
# ---------------------------------------------------------------------------

def _handle_submit(
    *,
    acc_id: int,
    account_key: str | None = None,
    tx_date: date,
    tx_time: time | None,
    tx_type: str,
    amount_rub: float | None,
    currency: str | None,
    category_id: int | None,
    counterparty: str,
    description: str,
    is_transfer: bool,
) -> None:
    if amount_rub is None:
        st.error("Введите сумму.")
        return

    amount_kopecks = format_amount_input_to_kopecks(
        amount_rub, is_income=(tx_type == "Доход"),
    )
    if amount_kopecks == 0:
        st.error("Сумма должна быть больше нуля.")
        return

    cp_clean = counterparty.strip() or None
    desc_clean = (description or "").strip() or None

    try:
        with st.spinner("Сохранение транзакции…"):
            with get_session() as session:
                tx = add_manual_transaction(
                    session,
                    account_id=acc_id,
                    date=tx_date,
                    time=tx_time,
                    amount=amount_kopecks,
                    currency=currency,
                    description=desc_clean or "",
                    counterparty_name=cp_clean,
                    category_id=category_id,
                    is_transfer=is_transfer,
                    account_key=account_key,
                )
                tx_id = tx.transaction_id
    except DuplicateTransactionError as e:
        st.error(
            f"Такая транзакция уже есть в базе "
            f"(id={e.existing_transaction_id})."
        )
        st.info(
            f"Найти её можно в разделе «Транзакции»: "
            f"дата **{format_date(tx_date)}**, "
            f"сумма **{format_amount(amount_kopecks)}**, "
            f"описание «{desc_clean or EMPTY}»."
        )
        return
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка добавления: {type(e).__name__}: {e}")
        with st.expander("Детали ошибки"):
            st.exception(e)
        return

    _clear_form_state()
    invalidate_transactions()
    st.session_state["add_tx_flash"] = (
        f"{format_amount(amount_kopecks)} · {format_date(tx_date)} · "
        f"{'перевод' if is_transfer else 'транзакция'} добавлена."
    )
    st.rerun()