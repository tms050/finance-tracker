"""Тесты форматтеров UI-4."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ui import formatters as f


def _cat(cid, name, parent_id=None, type_="expense"):
    return SimpleNamespace(
        category_id=cid, name=name,
        parent_category_id=parent_id, type=type_,
    )


# ---------- format_category_type_ru ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("income", "Доход"),
        ("expense", "Расход"),
        ("transfer", "Перевод"),
    ],
)
def test_category_type_ru_known(raw, expected):
    assert f.format_category_type_ru(raw) == expected


def test_category_type_ru_unknown():
    assert f.format_category_type_ru("weird") == "weird"


# ---------- format_category_parents ----------

def test_category_parents_empty():
    assert f.format_category_parents([]) == {}


def test_category_parents_flat():
    cats = [_cat(1, "Food"), _cat(2, "Transport")]
    assert f.format_category_parents(cats) == {1: "—", 2: "—"}


def test_category_parents_with_parent():
    cats = [_cat(1, "Food"), _cat(2, "Restaurants", parent_id=1)]
    assert f.format_category_parents(cats) == {1: "—", 2: "Food"}


def test_category_parents_orphan():
    """parent_id указывает на несуществующую категорию."""
    cats = [_cat(2, "Orphan", parent_id=999)]
    assert f.format_category_parents(cats) == {2: "—"}


def test_category_parents_chain():
    cats = [
        _cat(1, "A"),
        _cat(2, "B", parent_id=1),
        _cat(3, "C", parent_id=2),
    ]
    result = f.format_category_parents(cats)
    assert result[1] == "—"
    assert result[2] == "A"
    assert result[3] == "B"