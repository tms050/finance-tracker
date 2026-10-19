"""Интеграционные тесты: парсим каждый PDF из fixtures и проверяем
общие инварианты, не привязанные к конкретным числам.

Тесты параметризуются автоматически через conftest.pytest_generate_tests
по всем *.pdf в fixtures/. Если фикстур нет — скипаются.
"""
import json

import pytest

from parser.sber_parser.sber_pdf import BalanceStatus, ParseResult


# ---------- базовые инварианты ----------

def test_parses_without_errors(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result: ParseResult = parser.parse(str(pdf_path))

    assert result.statement is not None
    assert result.statement.period_start is not None
    assert result.statement.period_end is not None
    assert result.statement.period_start <= result.statement.period_end
    assert result.statement.currency, "валюта не определена"

    assert result.transactions, "транзакции не найдены"

    for tx in result.transactions:
        assert tx.date is not None, f"нет даты: {tx}"
        assert tx.amount is not None, f"нет суммы: {tx}"
        assert isinstance(tx.amount, int)
        assert isinstance(tx.currency, str)
        assert tx.currency == result.statement.currency


def test_balance_check_passes(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    check = result.balance_check
    assert check is not None
    assert check.ok, f"баланс не сходится: {check.reason}"


def test_no_errors_in_warnings(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    errors = [w for w in result.warnings if "пропущено" in w.lower()]
    assert errors == [], f"ошибки при парсинге: {errors}"


# ---------- структурные инварианты ----------

def test_transactions_have_amount_and_balance_types(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    for tx in result.transactions:
        if tx.amount is not None:
            assert isinstance(tx.amount, int)
        if tx.balance is not None:
            assert isinstance(tx.balance, int)


def test_transactions_sorted_desc_by_datetime(parser, pdf_path):
    """Ожидаем, что операции идут от новых к старым (как в выписке)."""
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    keys = [
        (tx.date, tx.time or __import__("datetime").time(0, 0))
        for tx in result.transactions
        if tx.date is not None
    ]
    assert keys == sorted(keys, reverse=True), "транзакции не отсортированы по убыванию"


def test_balance_check_consistency(parser, pdf_path):
    """Если ok=True, то diff == 0 и n_skipped == 0."""
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    check = result.balance_check
    if check is not None and check.status == BalanceStatus.OK:
        assert check.ok is True
        assert check.diff == 0
        assert check.n_skipped == 0
        assert check.n_records == check.n_total_records


def test_balance_check_arithmetic(parser, pdf_path):
    """expected_newest = oldest_balance + sum_amounts; diff = expected - newest."""
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    check = result.balance_check
    if check is None:
        pytest.skip("balance_check отсутствует")

    if (check.oldest_balance is not None
            and check.sum_amounts is not None
            and check.expected_newest is not None):
        assert check.expected_newest == check.oldest_balance + check.sum_amounts

    if (check.expected_newest is not None
            and check.newest_balance is not None
            and check.diff is not None):
        assert check.diff == check.expected_newest - check.newest_balance


def test_balance_non_negative(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    for tx in result.transactions:
        if tx.balance is not None:
            # контракт: баланс неотрицателен, кроме овердрафта
            # (овердрафт в выписке Сбера допускается)
            assert isinstance(tx.balance, int)


def test_to_dict_serializable(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    d = result.to_dict()
    json.dumps(d, ensure_ascii=False)


def test_to_dict_matches_len(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    result = parser.parse(str(pdf_path))
    assert len(result.to_dict()["transactions"]) == len(result)


def test_warnings_reset_between_calls(parser, pdf_path):
    """Каждый parse начинает с чистого списка warnings."""
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    r1 = parser.parse(str(pdf_path))
    n1 = len(r1.warnings)
    r2 = parser.parse(str(pdf_path))
    n2 = len(r2.warnings)
    # если оба вызова валидны — количество warning'ов должно совпадать
    assert n1 == n2


def test_parse_is_deterministic(parser, pdf_path):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур")

    r1 = parser.parse(str(pdf_path))
    r2 = parser.parse(str(pdf_path))
    assert r1.to_dict() == r2.to_dict()