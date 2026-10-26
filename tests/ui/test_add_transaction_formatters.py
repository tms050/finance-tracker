"""Тесты форматтеров UI-5."""
from __future__ import annotations

import pytest

from src.ui import formatters as f


@pytest.mark.parametrize(
    "value, is_income, expected",
    [
        (1500.50, True, 150050),
        (1500.50, False, -150050),
        (0.01, True, 1),
        (0.01, False, -1),
        (100, True, 10000),
        (100, False, -10000),
        (0.29, True, 29),      # float precision: 0.29*100 = 28.99...
        (0.29, False, -29),
        (1234.56, True, 123456),
        (1234.56, False, -123456),
        (99.99, True, 9999),
        (99.99, False, -9999),
    ],
)
def test_amount_input_to_kopecks(value, is_income, expected):
    assert f.format_amount_input_to_kopecks(value, is_income=is_income) == expected


def test_amount_input_none():
    assert f.format_amount_input_to_kopecks(None, is_income=True) == 0
    assert f.format_amount_input_to_kopecks(None, is_income=False) == 0


def test_amount_input_zero():
    assert f.format_amount_input_to_kopecks(0, is_income=True) == 0
    assert f.format_amount_input_to_kopecks(0, is_income=False) == 0


def test_amount_input_negative_normalized_by_sign():
    """Защита: даже если прилетит отрицательное — берём abs и ставим знак по radio."""
    assert f.format_amount_input_to_kopecks(-100, is_income=True) == 10000
    assert f.format_amount_input_to_kopecks(-100, is_income=False) == -10000


def test_amount_input_half_kopeck_rounds_up():
    """ROUND_HALF_UP: 0.005 → 0.01 (1 копейка)."""
    assert f.format_amount_input_to_kopecks(0.005, is_income=True) == 1