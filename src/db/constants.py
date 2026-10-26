"""Константы DB-слоя: версия хэша и допустимые значения для CHECK."""

from __future__ import annotations

from typing import Final

CURRENT_HASH_VERSION: Final[int] = 1
MIN_HASH_VERSION: Final[int] = 1

ACCOUNT_CURRENCIES: Final[tuple[str, ...]] = ("RUB", "USD", "EUR", "MULTI")
TRANSACTION_CURRENCIES: Final[tuple[str, ...]] = ("RUB", "USD", "EUR")
SOURCES: Final[tuple[str, ...]] = ("pdf", "csv", "api", "manual")
CATEGORY_TYPES: Final[tuple[str, ...]] = ("income", "expense", "transfer")
IS_TRANSFER_VALUES: Final[tuple[int, ...]] = (0, 1)
ERR_CURRENCY_UNSUPPORTED: Final[str] = "currency_unsupported"

def sql_in_list(values: tuple) -> str:
    """Рендерит кортеж в SQL-список для CheckConstraint.
    ВАЖНО: возвращает сырой SQL, экранирует только одиночные кавычки
    для строк. Предназначено ТОЛЬКО для in-code констант
    """
    return "(" + ", ".join(
        f"'{v}'" if isinstance(v, str) else str(v) for v in values
    ) + ")"