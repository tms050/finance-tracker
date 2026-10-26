"""UI-3: статистика - сводка + графики. Отметка переводов - отдельная страница."""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from src.db import get_session
from src.stats import get_summary
from src.transactions import list_transactions
from src.ui.components.data_loaders import load_transactions
from src.ui.components.metrics import metric_card
from src.ui.components.period_filter import render_period_filter
from src.ui.formatters import (
    format_amount,
    format_metric_pair,
    format_summary_period,
    format_date,
)


def render(account_id: int | None) -> None:
    if "stats_flash" in st.session_state:
        st.success(st.session_state.pop("stats_flash"))

    st.markdown("## Статистика")
    st.caption(
        "Сводка за выбранный период. Переводы между своими счетами "
        "не входят в доходы/расходы."
    )

    period = render_period_filter("stats")
    if period is None:
        return

    summary = _load_summary(account_id, period)
    if summary is None:
        return

    _render_metrics(summary)
    _render_state_caption(account_id, period, summary)

    st.divider()
    _render_charts(account_id, period)

    st.divider()
    _render_export_button(account_id, period)


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def _load_summary(account_id: int | None, period):
    date_from, date_to = period
    try:
        with st.spinner("Подсчёт статистики…"):
            with get_session() as session:
                return get_summary(
                    session,
                    account_id=account_id,
                    date_from=date_from,
                    date_to=date_to,
                )
    except ValueError as e:
        st.error(f"Ошибка фильтра: {e}")
        return None
    except Exception as e:
        st.error(f"Ошибка статистики: {type(e).__name__}: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return None


def _render_metrics(summary) -> None:
    if not summary.has_data:
        st.info("За выбранный период транзакций нет.")
        return

    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        metric_card(
            "Доходы",
            format_amount(summary.income),
            variant="positive",
            icon="trending_up",
        )
    with col2:
        metric_card(
            "Расходы",
            format_amount(-abs(summary.expense)),
            variant="negative",
            icon="trending_down",
        )
    with col3:
        net = summary.net
        variant = (
            "positive" if net > 0
            else "negative" if net < 0
            else "neutral"
        )
        metric_card(
            "Чистый поток",
            format_amount(net),
            variant=variant,
            icon="account_balance_wallet",
            hint="доходы − расходы",
        )
    with col4:
        metric_card(
            "Обычных / Переводов",
            format_metric_pair(summary.count, summary.transfer_count),
            icon="receipt_long",
            hint=f"всего {summary.total_count}",
        )


def _render_state_caption(
    account_id: int | None,
    period: tuple[date | None, date | None],
    summary,
) -> None:
    account_label = (
        "все счёта" if account_id is None else f"счёт #{account_id}"
    )
    date_from, date_to = period
    if date_from is None and date_to is None:
        period_label = "всё время"
    elif date_from is None:
        period_label = f"по {format_date(date_to)}"
    elif date_to is None:
        period_label = f"с {format_date(date_from)}"
    else:
        period_label = f"{format_date(date_from)} – {format_date(date_to)}"

    st.caption(
        f"{account_label} · {period_label} · "
        f"всего транзакций: **{summary.total_count}** "
        f"(переводов: {summary.transfer_count})"
    )


# ---------------------------------------------------------------------------
# Графики
# ---------------------------------------------------------------------------

def _render_charts(account_id: int | None, period) -> None:
    filters = _build_filters(account_id, period)
    try:
        with st.spinner("Подготовка графиков…"):
            rows, _total, cat_labels = load_transactions(
                filters, page=0, page_size=None,
            )
    except Exception as e:
        st.error(f"Ошибка загрузки данных: {type(e).__name__}: {e}")
        return

    if not rows:
        return

    df = _to_dataframe(rows)
    if df.empty:
        return

    # Переводы не участвуют в доходах/расходах.
    df_real = df[~df["is_transfer"]].copy()
    if df_real.empty:
        st.info("За период только переводы - строить графики не из чего.")
        return

    _render_flow_chart(df_real, period)
    st.divider()
    _render_top_categories(df_real, cat_labels)


def _build_filters(account_id: int | None, period) -> dict:
    filters: dict = {}
    if account_id is not None:
        filters["account_id"] = account_id
    if period[0] is not None:
        filters["date_from"] = period[0]
    if period[1] is not None:
        filters["date_to"] = period[1]
    return filters


def _to_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["amount_rub"] = df["amount"] / 100.0
    return df


def _render_flow_chart(df: pd.DataFrame, period) -> None:
    """Доходы vs расходы по дням (если период ≤ 31 день) или по месяцам."""
    span_days = _span_days(df, period)
    if span_days <= 31:
        df["bucket"] = df["date"].dt.strftime("%d.%m")
        subtitle = "по дням"
    else:
        df["bucket"] = df["date"].dt.strftime("%Y-%m")
        subtitle = "по месяцам"

    grouped = (
        df.assign(
            income=df["amount_rub"].where(df["amount_rub"] > 0, 0),
            expense=(-df["amount_rub"]).where(df["amount_rub"] < 0, 0),
        )
        .groupby("bucket", as_index=False)[["income", "expense"]]
        .sum()
    )

    long_df = grouped.melt(
        id_vars="bucket",
        value_vars=["income", "expense"],
        var_name="Тип",
        value_name="Сумма",
    )
    long_df["Тип"] = long_df["Тип"].map(
        {"income": "Доходы", "expense": "Расходы"}
    )

    chart = (
        alt.Chart(long_df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("bucket:N", title=None, sort=None),
            y=alt.Y("Сумма:Q", title="₽"),
            color=alt.Color(
                "Тип:N",
                scale=alt.Scale(
                    domain=["Доходы", "Расходы"],
                    range=["#16a34a", "#dc2626"],
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            xOffset="Тип:N",
            tooltip=[
                alt.Tooltip("bucket:N", title="Период"),
                alt.Tooltip("Тип:N"),
                alt.Tooltip("Сумма:Q", format=",.2f", title="₽"),
            ],
        )
        .properties(height=280)
    )

    with st.container(border=True):
        st.markdown(f"**Динамика доходов и расходов** {subtitle}")
        st.altair_chart(chart, use_container_width=True)


def _render_top_categories(df: pd.DataFrame, cat_labels: dict[int, str]) -> None:
    expenses = df[df["amount_rub"] < 0].copy()
    if expenses.empty:
        st.info("За период нет расходов.")
        return

    expenses["Категория"] = expenses["category_id"].map(
        lambda cid: cat_labels.get(cid, "Без категории")
        if cid else "Без категории"
    )
    top = (
        expenses.groupby("Категория", as_index=False)["amount_rub"]
        .sum()
        .assign(Сумма=lambda d: d["amount_rub"].abs())
        .nlargest(10, "Сумма")[["Категория", "Сумма"]]
        .sort_values("Сумма", ascending=True)
    )
    if top.empty:
        return

    chart = (
        alt.Chart(top)
        .mark_bar(color="#2563eb", cornerRadiusEnd=3)
        .encode(
            x=alt.X("Сумма:Q", title="₽"),
            y=alt.Y("Категория:N", sort=None, title=None),
            tooltip=[
                alt.Tooltip("Категория:N"),
                alt.Tooltip("Сумма:Q", format=",.2f", title="₽"),
            ],
        )
        .properties(height=max(220, len(top) * 28))
    )

    with st.container(border=True):
        st.markdown("**Топ-10 категорий расходов**")
        st.altair_chart(chart, use_container_width=True)


def _span_days(df: pd.DataFrame, period) -> int:
    if period[0] is not None and period[1] is not None:
        return (period[1] - period[0]).days
    if not df.empty:
        return (df["date"].max() - df["date"].min()).days
    return 0


# ---------------------------------------------------------------------------
# CSV-экспорт (как было)
# ---------------------------------------------------------------------------

def _render_export_button(account_id: int | None, period) -> None:
    filters = _build_filters(account_id, period)
    prepare_key = f"stats_csv|{account_id}|{period[0]}|{period[1]}"

    if prepare_key not in st.session_state:
        if st.button(
            "Подготовить CSV",
            icon=":material/download:",
            key=f"stats_csv_prepare|{prepare_key}",
        ):
            try:
                with st.spinner("Подготовка CSV…"):
                    st.session_state[prepare_key] = _build_csv(filters)
            except Exception as e:
                st.error(f"Ошибка подготовки CSV: {type(e).__name__}: {e}")
                with st.expander("Детали"):
                    st.exception(e)
                return
            st.rerun()
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        st.download_button(
            "Скачать CSV",
            data=st.session_state[prepare_key],
            file_name=f"stats_{date.today().isoformat()}.csv",
            mime="text/csv",
            key=f"stats_csv_download|{prepare_key}",
            use_container_width=True,
        )
    with col2:
        if st.button(
            "Очистить",
            key=f"stats_csv_clear|{prepare_key}",
            use_container_width=True,
        ):
            st.session_state.pop(prepare_key, None)
            st.rerun()


def _build_csv(filters: dict) -> bytes:
    with get_session() as session:
        txs = list_transactions(session, **filters)

    rows = [
        {
            "ID": t.transaction_id,
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
        }
        for t in txs
    ]
    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8-sig")