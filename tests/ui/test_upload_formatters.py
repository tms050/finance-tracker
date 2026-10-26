"""Тесты форматтеров UI-2 (без Streamlit, без БД)."""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

import pytest

from src.ui import formatters as f


# ---------- format_balance_check ----------

def _bc(status, diff=None, n_skipped=0):
    return SimpleNamespace(
        status=SimpleNamespace(value=status), diff=diff, n_skipped=n_skipped,
    )


def test_balance_check_none():
    assert f.format_balance_check(None) == ("info", "Сверка баланса недоступна")


def test_balance_check_ok():
    level, msg = f.format_balance_check(_bc("ok"))
    assert level == "success"
    assert "сошёлся" in msg


def test_balance_check_mismatch_shows_diff():
    level, msg = f.format_balance_check(_bc("mismatch", diff=-12345))
    assert level == "error"
    assert "−123,45" in msg


def test_balance_check_incomplete_shows_skipped():
    level, msg = f.format_balance_check(_bc("incomplete", n_skipped=3))
    assert level == "warning"
    assert "сверить баланс" in msg
    assert "3" in msg


def test_balance_check_insufficient_data():
    level, msg = f.format_balance_check(_bc("insufficient_data"))
    assert level == "info"
    assert "Недостаточно" in msg


def test_balance_check_unknown_status():
    level, msg = f.format_balance_check(_bc("weird"))
    assert level == "info"
    assert "weird" in msg


# ---------- format_import_status ----------

@pytest.mark.parametrize(
    "status, level",
    [
        ("ok", "success"),
        ("duplicate_statement", "error"),
        ("no_valid_transactions", "warning"),
    ],
)
def test_format_import_status_known(status, level):
    got_level, _ = f.format_import_status(status)
    assert got_level == level


def test_format_import_status_unknown():
    level, msg = f.format_import_status("weird")
    assert level == "info"
    assert "weird" in msg


# ---------- format_parse_meta ----------

def _stmt(**kwargs):
    defaults = dict(
        fio=None, account_number_masked=None, card_number_masked=None,
        currency=None, period_start=None, period_end=None,
        open_date=None, close_date=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_format_parse_meta_all_none():
    meta = f.format_parse_meta(_stmt())
    labels = [label for label, _ in meta]
    assert labels == ["ФИО", "Счёт", "Карта", "Валюта", "Период", "Открыт", "Закрыт"]
    for _, value in meta:
        assert value == "—"


def test_format_parse_meta_full():
    meta = dict(f.format_parse_meta(_stmt(
        fio="Иванов И.И.",
        account_number_masked="**** 1234",
        card_number_masked="**** 5678",
        currency="RUB",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        open_date=date(2020, 5, 1),
        close_date=None,
    )))
    assert meta["ФИО"] == "Иванов И.И."
    assert meta["Счёт"] == "**** 1234"
    assert meta["Карта"] == "**** 5678"
    assert meta["Валюта"] == "RUB"
    assert meta["Период"] == "01.01.2024 – 31.01.2024"
    assert meta["Открыт"] == "01.05.2020"
    assert meta["Закрыт"] == "—"


# ---------- format_skipped_* ----------

def test_format_skipped_intra():
    skip = SimpleNamespace(original_index=3, transaction_hash="a" * 16)
    # original_index=3 → 4-я транзакция в выписке (1-based)
    assert f.format_skipped_intra(skip) == "#4 · hash aaaaaaaaaaaa…"


def test_format_skipped_cross():
    skip = SimpleNamespace(
        original_index=5,
        transaction_hash="b" * 16,
        existing_transaction_id=42,
    )
    result = f.format_skipped_cross(skip)
    assert "#6" in result
    assert "bbbbbbbbbbbb" in result
    assert "дубликат tx_id=42" in result


# ---------- format_rejected_row ----------

def test_format_rejected_row_full():
    rejected = SimpleNamespace(
        date=date(2024, 1, 15),
        time=None,
        amount=None,
        currency=None,
        description=None,
        validation_errors=("missing_date", "currency_mismatch"),
    )
    row = f.format_rejected_row(rejected)
    assert row["Ошибки"] == "нет даты, валюта не совпадает со счётом"


def test_format_rejected_row_empty():
    r = SimpleNamespace(
        date=None, time=None, amount=None, currency=None,
        description=None, validation_errors=(),
    )
    row = f.format_rejected_row(r)
    assert row["Дата"] == "—"
    assert row["Сумма"] == "—"
    assert row["Ошибки"] == "—"