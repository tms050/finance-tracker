"""Тесты чистых функций src.ui.formatters."""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

import pytest

from src.ui import formatters as f


# ---------- format_amount ----------

@pytest.mark.parametrize(
    "amount, expected",
    [
        (123456, "+1\u00a0234,56"),
        (1, "+0,01"),
        (100, "+1,00"),
        (-123456, "\u22121\u00a0234,56"),
        (-50, "\u22120,50"),
        (0, "0,00"),
        (None, "—"),
        (12_345_678, "+123\u00a0456,78"),
    ],
)
def test_format_amount(amount, expected):
    assert f.format_amount(amount) == expected


def test_format_amount_uses_unicode_minus_not_hyphen():
    assert "\u2212" in f.format_amount(-1)
    assert "-" not in f.format_amount(-1)


# ---------- amount_style ----------

def test_amount_style_positive_is_green():
    assert f.COLOR_INCOME in f.amount_style(100)


def test_amount_style_negative_is_red():
    assert f.COLOR_EXPENSE in f.amount_style(-100)


def test_amount_style_zero_and_none_have_no_color():
    assert f.COLOR_INCOME not in f.amount_style(0)
    assert f.COLOR_EXPENSE not in f.amount_style(0)
    assert f.COLOR_INCOME not in f.amount_style(None)


def test_amount_style_right_aligned_always():
    for v in (None, 0, 1, -1):
        assert "text-align: right;" in f.amount_style(v)


# ---------- format_date / format_time ----------

def test_format_date():
    assert f.format_date(date(2024, 1, 15)) == "15.01.2024"
    assert f.format_date(None) == "—"


def test_format_time():
    assert f.format_time(time(12, 34)) == "12:34"
    assert f.format_time(time(0, 0)) == "00:00"
    assert f.format_time(None) == "—"


# ---------- format_transfer ----------

@pytest.mark.parametrize("value, expected", [(1, "✅"), (0, "❌"), (True, "✅"), (False, "❌")])
def test_format_transfer(value, expected):
    assert f.format_transfer(value) == expected


# ---------- format_optional_text ----------

def test_format_optional_text_none_and_empty():
    assert f.format_optional_text(None) == "—"
    assert f.format_optional_text("") == "—"
    assert f.format_optional_text("   ") == "—"


def test_format_optional_text_strips():
    assert f.format_optional_text("  hello  ") == "hello"


def test_format_optional_text_truncates():
    long = "a" * 150
    result = f.format_optional_text(long, max_len=100)
    assert len(result) == 100
    assert result.endswith("…")
    assert result[:-1] == "a" * 99


def test_format_optional_text_no_truncation_when_short():
    assert f.format_optional_text("hello", max_len=10) == "hello"
    assert f.format_optional_text("a" * 10, max_len=10) == "a" * 10


# ---------- format_account_label ----------

def test_format_account_label_full():
    assert f.format_account_label("Sber", "Main", "**** 1234") == "Sber · Main · **** 1234"


def test_format_account_label_closed():
    assert (
        f.format_account_label("Sber", "Main", "**** 1234", is_closed=True)
        == "Sber · Main · **** 1234 (закрыт)"
    )


def test_format_account_label_partial():
    assert f.format_account_label("Sber", None, None) == "Sber"
    assert f.format_account_label(None, None, None) == "Счёт"

def test_format_account_label_dedup_bank_and_number():
    """account_name уже содержит банк + номер — не дублируем."""
    assert f.format_account_label(
        "Сбербанк", "Сбербанк **** 1234", "**** 1234",
    ) == "Сбербанк **** 1234"


def test_format_account_label_dedup_bank_only():
    """account_name содержит банк, но не номер."""
    assert f.format_account_label(
        "Сбербанк", "Сбербанк Основной", "**** 1234",
    ) == "Сбербанк Основной · **** 1234"


def test_format_account_label_dedup_number_only():
    """account_name содержит номер, но не банк."""
    assert f.format_account_label(
        "Сбербанк", "Основной **** 1234", "**** 1234",
    ) == "Сбербанк · Основной **** 1234"


def test_format_account_label_dedup_closed():
    assert f.format_account_label(
        "Сбербанк", "Сбербанк **** 1234", "**** 1234", is_closed=True,
    ) == "Сбербанк **** 1234 (закрыт)"


def test_format_account_label_case_insensitive_dedup():
    assert f.format_account_label(
        "СБЕРБАНК", "сбербанк **** 1234", "**** 1234",
    ) == "сбербанк **** 1234"

# ---------- build_category_labels ----------

def _cat(cid, name, pid=None):
    return SimpleNamespace(category_id=cid, name=name, parent_category_id=pid)


def test_build_category_labels_flat():
    cats = [_cat(1, "Food"), _cat(2, "Transport")]
    assert f.build_category_labels(cats) == {1: "Food", 2: "Transport"}


def test_build_category_labels_with_parent():
    cats = [_cat(1, "Food"), _cat(2, "Restaurants", pid=1)]
    assert f.build_category_labels(cats) == {1: "Food", 2: "Food / Restaurants"}


def test_build_category_labels_missing_parent_falls_back_to_name():
    cats = [_cat(2, "Orphan", pid=999)]
    assert f.build_category_labels(cats) == {2: "Orphan"}


def test_build_category_labels_empty():
    assert f.build_category_labels([]) == {}

def test_format_import_status_ok_no_warnings():
    assert f.format_import_status("ok") == ("success", "Импорт завершён")

def test_format_import_status_ok_with_warnings():
    level, msg = f.format_import_status("ok", warnings_count=3)
    assert level == "warning"
    assert "3 предупреждений" in msg

def test_format_parse_meta_period_one_side():
    info = SimpleNamespace(
        period_start=date(2024, 1, 1), period_end=None,
        fio=None, account_number_masked=None,
        card_number_masked=None, currency=None,
        open_date=None, close_date=None,
    )
    meta = dict(f.format_parse_meta(info))
    assert meta["Период"] == "с 01.01.2024"

def test_format_rejected_row_errors_not_char_joined():
    rejected = SimpleNamespace(
        date=None, time=None, amount=None, currency=None,
        description=None,
        validation_errors=("missing_date", "missing_amount"),
    )
    row = f.format_rejected_row(rejected)
    assert row["Ошибки"] == "нет даты, нет суммы"   # не "н,е,т,..."