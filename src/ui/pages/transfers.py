"""UI-3b: отметка переводов между своими счетами."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.db import get_session
from src.transactions import list_transactions, update_transaction
from src.ui.components.data_loaders import invalidate_transactions, load_transactions
from src.ui.components.period_filter import render_period_filter
from src.ui.formatters import (
    EMPTY,
    format_amount,
    format_date,
    format_optional_text,
    format_time,
    summarize_changes,
)

EDIT_LIMIT = 200

_EDITABLE_COLS = [
    "Дата", "Время", "Сумма", "Валюта", "Категория",
    "Контрагент", "Описание", "Перевод?",
]


def render(account_id: int | None) -> None:
    if "transfers_flash" in st.session_state:
        st.success(st.session_state.pop("transfers_flash"))

    st.markdown("## Переводы")
    st.caption(
        "Отметьте транзакции, которые являются переводами между "
        "вашими счетами. Такие транзакции исключаются из доходов "
        "и расходов в статистике."
    )

    period = render_period_filter("transfers")
    if period is None:
        return

    _render_editor(account_id, period)


# ---------------------------------------------------------------------------
# Редактор
# ---------------------------------------------------------------------------

def _render_editor(
    account_id: int | None,
    period: tuple[date | None, date | None],
) -> None:
    transfer_filter = st.radio(
        "Показывать",
        options=["Все", "Только переводы", "Только не-переводы"],
        horizontal=True,
        key="transfers_filter",
    )

    filters = _build_filters(account_id, period, transfer_filter)

    try:
        with st.spinner("Загрузка транзакций…"):
            raw, total, cat_labels = load_transactions(
                filters, page=0, page_size=EDIT_LIMIT,
            )
    except ValueError as e:
        st.error(f"Ошибка фильтра: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка загрузки: {type(e).__name__}: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return

    if total == 0:
        st.info("Транзакций по фильтру нет.")
        return
    if total > EDIT_LIMIT:
        st.warning(
            f"Показаны первые {EDIT_LIMIT} из {total}. "
            f"Уточните период, чтобы увидеть остальные."
        )

    df = _build_editor_df(raw, cat_labels)
    original_df = df.copy()

    editor_key = (
        f"transfers_editor|{account_id}|"
        f"{period[0]}|{period[1]}|{transfer_filter}"
    )

    edited_df = st.data_editor(
        df,
        key=editor_key,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in df.columns if c != "Перевод?"],
        column_order=_EDITABLE_COLS,
        column_config={
            "Дата": st.column_config.TextColumn("Дата", width="small"),
            "Время": st.column_config.TextColumn("Время", width="small"),
            "Сумма": st.column_config.TextColumn("Сумма", width="small"),
            "Валюта": st.column_config.TextColumn("Валюта", width="small"),
            "Категория": st.column_config.TextColumn("Категория", width="medium"),
            "Контрагент": st.column_config.TextColumn("Контрагент", width="medium"),
            "Описание": st.column_config.TextColumn("Описание", width="large"),
            "Перевод?": st.column_config.CheckboxColumn(
                "Перевод?",
                default=False,
                help="Отметьте, если перевод между своими счетами",
                width="small",
            ),
        },
    )

    changes = summarize_changes(original_df, edited_df)

    if changes:
        st.warning(f"Несохранённых изменений: {len(changes)}")
        if st.button(
            "Сохранить изменения",
            icon=":material/save:",
            type="primary",
            key="transfers_save",
        ):
            _save_changes(changes, editor_key)
        st.caption(
            "При смене периода / фильтра несохранённые изменения теряются."
        )
    else:
        st.caption("Нет несохранённых изменений.")


def _build_filters(
    account_id: int | None,
    period: tuple[date | None, date | None],
    transfer_filter: str,
) -> dict:
    filters: dict = {}
    if account_id is not None:
        filters["account_id"] = account_id
    if period[0] is not None:
        filters["date_from"] = period[0]
    if period[1] is not None:
        filters["date_to"] = period[1]
    if transfer_filter == "Только переводы":
        filters["is_transfer"] = True
    elif transfer_filter == "Только не-переводы":
        filters["is_transfer"] = False
    return filters


def _build_editor_df(
    rows: list[dict], cat_labels: dict[int, str],
) -> pd.DataFrame:
    data = []
    for r in rows:
        data.append({
            "ID": r["transaction_id"],
            "Дата": format_date(r["date"]),
            "Время": format_time(r["time"]),
            "Сумма": format_amount(r["amount"]),
            "Валюта": r["currency"] or EMPTY,
            "Категория": (
                cat_labels.get(r["category_id"], EMPTY)
                if r["category_id"] else EMPTY
            ),
            "Контрагент": format_optional_text(r["counterparty_name"]),
            "Описание": format_optional_text(r["description"]),
            "Перевод?": bool(r["is_transfer"]),
        })
    return pd.DataFrame(data)


def _save_changes(changes: dict[int, bool], editor_key: str) -> None:
    try:
        with st.spinner("Сохранение изменений…"):
            with get_session() as session:
                for tx_id, new_value in changes.items():
                    update_transaction(
                        session, tx_id, is_transfer=bool(new_value),
                    )
    except Exception as e:
        st.error(f"Ошибка сохранения: {type(e).__name__}: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return

    st.session_state.pop(editor_key, None)
    invalidate_transactions()
    st.session_state["transfers_flash"] = (
        f"Обновлено транзакций: {len(changes)}"
    )
    st.rerun()