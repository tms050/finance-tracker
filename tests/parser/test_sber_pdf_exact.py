"""
Точные эталонные проверки конкретных PDF.
Значения ниже нужно заполнить под свои фикстуры. Если файла нет -
соответствующий тест пропускается.
"""
import datetime
from pathlib import Path

import pytest

from src.parser.sber_parser.sber_pdf import BalanceStatus


# --- таблица эталонов ---------------------------------------------------
#
# Ключ - stem имени файла в fixtures/.
# Значение - dict с ожидаемыми полями. Любое поле можно опустить,
# тогда соответствующий блок проверок будет пропущен.
#
# Пример заполнения:
#
# EXACT = {
#     "sber_2024_03_debit": {
#         "period_start": datetime.date(2024, 3, 1),
#         "period_end":   datetime.date(2024, 3, 31),
#         "n_transactions": 42,
#         "balance_ok": True,
#         "first": {
#             "amount": -150000,
#             "counterparty_name": "VODA MOSKVA RUS",
#             "currency": "RUB",
#         },
#         "last": {
#             "amount": 150000,
#             "counterparty_name": "Перевод от Иванов Иван Иванович",
#         },
#     },
# }
EXACT: dict[str, dict] = {
    # TODO: заполнить эталонами
}


def _case(stem: str) -> dict:
    if stem not in EXACT:
        pytest.skip(f"эталон для {stem} не задан в EXACT")
    return EXACT[stem]


def _require_fixture(fixtures_dir: Path, stem: str) -> Path:
    pdf_path = fixtures_dir / f"{stem}.pdf"
    if not pdf_path.exists():
        pytest.skip(f"фикстура {pdf_path.name} не найдена")
    return pdf_path


@pytest.mark.parametrize("stem", list(EXACT.keys()) or ["__no_exact_yet__"])
def test_exact(parser, fixtures_dir, stem):
    if stem == "__no_exact_yet__":
        pytest.skip("нет заполненных эталонов в EXACT")

    pdf_path = _require_fixture(fixtures_dir, stem)
    expected = _case(stem)

    result = parser.parse(str(pdf_path))

    # --- метаданные выписки ---
    if "period_start" in expected:
        assert result.statement.period_start == expected["period_start"]
    if "period_end" in expected:
        assert result.statement.period_end == expected["period_end"]
    if "currency" in expected:
        assert result.statement.currency == expected["currency"]
    if "fio" in expected:
        assert result.statement.fio == expected["fio"]
    if "account_number_masked" in expected:
        assert result.statement.account_number_masked == expected["account_number_masked"]

    # --- количество транзакций ---
    if "n_transactions" in expected:
        assert len(result.transactions) == expected["n_transactions"]

    # --- сверка баланса ---
    if "balance_ok" in expected:
        assert result.balance_check is not None
        assert result.balance_check.ok == expected["balance_ok"]
    if "balance_status" in expected:
        assert result.balance_check.status == expected["balance_status"]
    if "balance_diff" in expected:
        assert result.balance_check.diff == expected["balance_diff"]

    # --- первая / последняя транзакция ---
    if "first" in expected:
        assert result.transactions, "нет транзакций"
        _check_tx(result.transactions[0], expected["first"])
    if "last" in expected:
        assert result.transactions, "нет транзакций"
        _check_tx(result.transactions[-1], expected["last"])


def _check_tx(tx, expected: dict) -> None:
    for field, value in expected.items():
        actual = getattr(tx, field)
        assert actual == value, f"tx.{field}: ожидалось {value!r}, получено {actual!r}"