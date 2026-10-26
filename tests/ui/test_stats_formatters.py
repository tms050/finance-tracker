"""Тесты форматтеров UI-3 (без Streamlit, без БД)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.ui import formatters as f


# ---------- format_summary_period ----------

def test_period_current_month():
    today = date(2024, 3, 15)
    assert f.format_summary_period("Текущий месяц", today) == (date(2024, 3, 1), date(2024, 3, 15))


def test_period_previous_month():
    today = date(2024, 3, 15)
    assert f.format_summary_period("Прошлый месяц", today) == (date(2024, 2, 1), date(2024, 2, 29))


def test_period_previous_month_from_january():
    today = date(2024, 1, 15)
    assert f.format_summary_period("Прошлый месяц", today) == (date(2023, 12, 1), date(2023, 12, 31))


def test_period_previous_month_leap_feb():
    today = date(2024, 3, 1)
    assert f.format_summary_period("Прошлый месяц", today) == (date(2024, 2, 1), date(2024, 2, 29))


def test_period_current_year():
    today = date(2024, 3, 15)
    assert f.format_summary_period("Текущий год", today) == (date(2024, 1, 1), date(2024, 3, 15))


def test_period_all_time():
    assert f.format_summary_period("Всё время") == (None, None)


def test_period_unknown_returns_none():
    assert f.format_summary_period("weird") == (None, None)


# ---------- format_metric_pair ----------

def test_metric_pair():
    assert f.format_metric_pair(10, 3) == "10 / 3"
    assert f.format_metric_pair(0, 0) == "0 / 0"
    assert f.format_metric_pair(1, 0) == "1 / 0"


# ---------- format_amount_for_delta ----------

def test_delta_positive():
    assert f.format_amount_for_delta(123456) == "+1\u00a0234,56"


def test_delta_negative_ascii_minus():
    out = f.format_amount_for_delta(-123456)
    assert out == "-1\u00a0234,56"
    assert "\u2212" not in out


def test_delta_zero_and_none():
    assert f.format_amount_for_delta(0) == "0,00"
    assert f.format_amount_for_delta(None) == "0,00"


# ---------- summarize_changes ----------

def _df(ids, flags):
    return pd.DataFrame({"ID": ids, "Перевод?": flags})


def test_summarize_no_changes():
    assert f.summarize_changes(_df([1, 2], [False, True]), _df([1, 2], [False, True])) == {}


def test_summarize_one_change():
    assert f.summarize_changes(_df([1, 2], [False, False]), _df([1, 2], [True, False])) == {1: True}


def test_summarize_multiple_changes():
    orig = _df([1, 2, 3], [False, True, False])
    edit = _df([1, 2, 3], [True, False, True])
    assert f.summarize_changes(orig, edit) == {1: True, 2: False, 3: True}


def test_summarize_reordered_rows():
    """Streamlit может отсортировать — матчим по ID, не по позиции.

    Строки переставлены (3, 1, 2), но единственное реальное изменение —
    у tx_id=2 снят флаг (True -> False).
    """
    orig = _df([1, 2, 3], [False, True, False])
    edit = _df([3, 1, 2], [False, False, False])
    assert f.summarize_changes(orig, edit) == {2: False}


def test_summarize_reordered_rows_true_change():
    """Перестановка + реальное изменение False -> True для tx_id=3."""
    orig = _df([1, 2, 3], [False, True, False])
    edit = _df([3, 1, 2], [True, False, True])
    assert f.summarize_changes(orig, edit) == {3: True}


def test_summarize_none_inputs():
    assert f.summarize_changes(None, None) == {}
    assert f.summarize_changes(None, _df([1], [False])) == {}
    assert f.summarize_changes(_df([1], [False]), None) == {}


def test_summarize_empty_dfs():
    assert f.summarize_changes(pd.DataFrame(), pd.DataFrame()) == {}