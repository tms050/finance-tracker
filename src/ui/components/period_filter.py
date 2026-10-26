"""Общий фильтр периода для страниц «Статистика» и «Переводы»."""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.ui.formatters import format_summary_period

PRESETS = [
    "Последние 7 дней",
    "Последние 30 дней",
    "Текущий месяц",
    "Прошлый месяц",
    "Прошлый квартал",
    "Текущий год",
    "Всё время",
    "Свой период",
]


def render_period_filter(
    key_prefix: str,
) -> tuple[date | None, date | None] | None:
    """Радио-пресет + кастомный диапазон. Возвращает (from, to) или None при ошибке."""
    preset = st.radio(
        "Период",
        options=PRESETS,
        horizontal=True,
        key=f"{key_prefix}_period_preset",
    )
    if preset != "Свой период":
        return format_summary_period(preset)

    date_range = st.date_input(
        "Диапазон дат",
        value=(date.today().replace(day=1), date.today()),
        key=f"{key_prefix}_custom_range",
    )
    dates = (
        list(date_range)
        if isinstance(date_range, (tuple, list))
        else [date_range]
    )
    date_from = dates[0] if dates and dates[0] else None
    date_to = dates[1] if len(dates) >= 2 and dates[1] else None

    if date_from is not None and date_to is not None and date_from > date_to:
        st.error("Дата «с» не может быть позже даты «по».")
        return None

    return date_from, date_to