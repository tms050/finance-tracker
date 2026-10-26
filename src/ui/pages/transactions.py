"""UI-1: список транзакций с фильтрами, пагинацией, пустыми состояниями."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.db import get_session
from src.transactions import list_transactions
from src.ui.components.data_loaders import load_transactions
from src.ui.formatters import (
    EMPTY,
    format_amount,
    format_date,
    format_optional_text,
    format_time,
    format_transfer,
)

PAGE_SIZE = 50

_FILTER_KEYS = (
    "tx_filters", "tx_no_dates", "tx_date_range",
    "tx_cat_idx", "tx_transfer_mode", "tx_search",
)


def render(account_id: int | None) -> None:
    st.markdown("## Транзакции")
    _render_filters()
    _render_list(account_id)


# ---------- загрузка ----------

def _load_rows(filters: dict, page: int) -> tuple[list[dict], int]:
    with st.spinner("Загрузка транзакций…"):
        raw, total, cat_labels = load_transactions(
            filters, page=page, page_size=PAGE_SIZE,
        )
    rows = []
    for r in raw:
        rows.append({
            "Дата": format_date(r["date"]),
            "Время": format_time(r["time"]),
            "Сумма": format_amount(r["amount"]),
            "Валюта": r["currency"] or EMPTY,
            "Категория": (
                cat_labels.get(r["category_id"], EMPTY)
                if r["category_id"] else EMPTY
            ),
            "Контрагент": format_optional_text(r["counterparty_name"]),
            "Описание": format_optional_text(r["description"], max_len=100),
            "Перевод?": format_transfer(r["is_transfer"]),
            "_amount_raw": r["amount"],
        })
    return rows, total


# ---------- фильтры ----------

def _build_category_options(cat_labels: dict[int, str]) -> list[tuple[int | None, str]]:
    opts: list[tuple[int | None, str]] = [(None, "Все категории")]
    opts.extend(sorted(cat_labels.items(), key=lambda kv: kv[1]))
    return opts


def _clear_filters() -> None:
    for k in _FILTER_KEYS:
        st.session_state.pop(k, None)
    st.session_state["tx_page"] = 0


def _render_filters() -> None:
    from src.ui.components.data_loaders import load_category_labels
    cat_labels = load_category_labels()

    with st.expander("Фильтры", expanded=True):
        no_dates = st.checkbox(
            "Без ограничения дат",
            value=True,
            key="tx_no_dates",
        )

        cat_options = _build_category_options(cat_labels)

        with st.form("tx_filters_form"):
            search = st.text_input(
                "Поиск по описанию / контрагенту",
                key="tx_search",
                placeholder="например, «Пятёрочка» или «Оплата»",
            )

            col1, col2 = st.columns(2)

            with col1:
                date_range = st.date_input(
                    "Период",
                    value=(date.today() - timedelta(days=30), date.today()),
                    disabled=no_dates,
                    key="tx_date_range",
                )

            with col2:
                cat_idx = st.selectbox(
                    "Категория",
                    options=range(len(cat_options)),
                    format_func=lambda i: cat_options[i][1],
                    key="tx_cat_idx",
                )
                transfer_mode = st.radio(
                    "Переводы",
                    options=["Все", "Только обычные", "Только переводы"],
                    horizontal=True,
                    key="tx_transfer_mode",
                )

            submitted = st.form_submit_button("Применить", type="primary")

        reset_clicked = st.button("Сбросить фильтры", key="tx_reset")

    if reset_clicked:
        _clear_filters()
        st.rerun()

    if submitted:
        st.session_state["tx_filters"] = _collect_filters(
            no_dates=no_dates,
            date_range=date_range,
            cat_options=cat_options,
            cat_idx=cat_idx,
            transfer_mode=transfer_mode,
            search=search,
        )
        st.session_state["tx_page"] = 0
        st.rerun()


def _collect_filters(
    *,
    no_dates: bool,
    date_range,
    cat_options: list[tuple[int | None, str]],
    cat_idx: int,
    transfer_mode: str,
    search: str,
) -> dict:
    filters: dict = {}

    query = (search or "").strip()
    if query:
        filters["description_query"] = query

    if not no_dates:
        dates = list(date_range) if isinstance(date_range, (tuple, list)) else [date_range]
        if dates and dates[0] is not None:
            filters["date_from"] = dates[0]
        if len(dates) >= 2 and dates[1] is not None:
            filters["date_to"] = dates[1]

    cat_id = cat_options[cat_idx][0]
    if cat_id is not None:
        filters["category_id"] = cat_id

    if transfer_mode == "Только обычные":
        filters["is_transfer"] = False
    elif transfer_mode == "Только переводы":
        filters["is_transfer"] = True

    return filters


# ---------- список ----------

def _render_list(account_id: int | None) -> None:
    filters = dict(st.session_state.get("tx_filters", {}))
    if account_id is not None:
        filters["account_id"] = account_id

    page = st.session_state.get("tx_page", 0)

    rows, total = _load_rows(filters, page)

    if total == 0:
        _render_empty_state(filters)
        return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page >= total_pages:
        st.session_state["tx_page"] = total_pages - 1
        st.rerun()

    page_sum = sum(r["_amount_raw"] for r in rows)

    st.caption(
        f"Показано {page * PAGE_SIZE + 1}–"
        f"{min((page + 1) * PAGE_SIZE, total)} из {total} · "
        f"Сумма на странице: {format_amount(page_sum)}"
    )

    df = pd.DataFrame(rows).reset_index(drop=True)
    display_df = df.drop(columns=["_amount_raw"])

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Дата": st.column_config.TextColumn("Дата", width="small"),
            "Время": st.column_config.TextColumn("Время", width="small"),
            "Сумма": st.column_config.TextColumn("Сумма", width="small"),
            "Валюта": st.column_config.TextColumn("Валюта", width="small"),
            "Категория": st.column_config.TextColumn("Категория", width="medium"),
            "Контрагент": st.column_config.TextColumn("Контрагент", width="medium"),
            "Описание": st.column_config.TextColumn("Описание", width="large"),
            "Перевод?": st.column_config.TextColumn("Перевод?", width="small"),
        },
    )

    _render_pagination(page, total_pages)

    st.divider()
    _render_export_button(filters)


def _render_empty_state(filters: dict) -> None:
    user_filters = set(filters) - {"account_id"}

    if user_filters:
        st.info("По фильтрам ничего не найдено.")
        if st.button("Сбросить фильтры", key="tx_empty_reset"):
            _clear_filters()
            st.rerun()
    elif filters.get("account_id") is not None:
        st.info(
            "У этого счёта пока нет транзакций. Загрузите выписку "
            "во вкладке «Загрузка» или добавьте вручную "
            "во вкладке «Добавить»."
        )
    else:
        st.info(
            "Транзакций нет. Загрузите первую выписку "
            "во вкладке «Загрузка»."
        )


def _render_pagination(page: int, total_pages: int) -> None:
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button(
            "Назад",
            icon=":material/chevron_left:",
            disabled=page == 0,
            use_container_width=True,
            key="tx_prev",
        ):
            st.session_state["tx_page"] = page - 1
            st.rerun()
    with col_info:
        st.markdown(
            f"<div style='text-align:center; padding-top:8px;'>"
            f"Страница {page + 1} из {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button(
            "Вперёд",
            icon=":material/chevron_right:",
            disabled=page >= total_pages - 1,
            use_container_width=True,
            key="tx_next",
        ):
            st.session_state["tx_page"] = page + 1
            st.rerun()


# ---------- CSV-экспорт ----------

def _render_export_button(filters: dict) -> None:
    if "tx_csv_data" not in st.session_state:
        if st.button(
            "Подготовить CSV",
            icon=":material/download:",
            key="tx_csv_prepare",
        ):
            try:
                with st.spinner("Подготовка CSV…"):
                    csv_bytes = _build_csv(filters)
            except Exception as e:
                st.error(f"Ошибка подготовки CSV: {type(e).__name__}: {e}")
                with st.expander("Детали"):
                    st.exception(e)
                return
            st.session_state["tx_csv_data"] = csv_bytes
            st.session_state["tx_csv_name"] = _csv_filename(filters)
            st.rerun()
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        st.download_button(
            "Скачать CSV",
            data=st.session_state["tx_csv_data"],
            file_name=st.session_state["tx_csv_name"],
            mime="text/csv",
            key="tx_csv_download",
            use_container_width=True,
        )
    with col2:
        if st.button("Очистить", key="tx_csv_clear", use_container_width=True):
            st.session_state.pop("tx_csv_data", None)
            st.session_state.pop("tx_csv_name", None)
            st.rerun()


def _build_csv(filters: dict) -> bytes:
    with get_session() as session:
        txs = list_transactions(session, **filters)

    rows = []
    for t in txs:
        rows.append({
            "Дата": t.date.isoformat() if t.date else "",
            "Время": t.time.isoformat() if t.time else "",
            "Сумма (коп.)": t.amount,
            "Валюта": t.currency or "",
            "Описание": t.description or "",
            "Контрагент": t.counterparty_name or "",
            "Перевод": "да" if t.is_transfer else "нет",
            "Категория ID": t.category_id or "",
            "raw_category": t.raw_category or "",
            "source": t.source,
        })

    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8-sig")


def _csv_filename(filters: dict) -> str:
    parts = ["transactions"]
    if filters.get("account_id") is not None:
        parts.append(f"acc{filters['account_id']}")
    if filters.get("date_from"):
        parts.append(f"from-{filters['date_from'].isoformat()}")
    if filters.get("date_to"):
        parts.append(f"to-{filters['date_to'].isoformat()}")
    parts.append(date.today().isoformat())
    return "_".join(parts) + ".csv"