"""Парсинг значений, связанных с деньгами"""
import re
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

_CURRENCY_ALIASES: dict[str, str] = {
    # RUB
    "₽": "RUB", "руб": "RUB", "р": "RUB",
    "rur": "RUB", "rub": "RUB", "российский рубль": "RUB", "рубль": "RUB", "рублей": "RUB",
    # USD
    "$": "USD", "usd": "USD", "долл": "USD",
    # EUR
    "€": "EUR", "eur": "EUR", "евро": "EUR",
    # KZT
    "₸": "KZT", "kzt": "KZT", "тенге": "KZT",
    # UAH
    "₴": "UAH", "uah": "UAH", "гривна": "UAH",
    # GBP
    "£": "GBP", "gbp": "GBP", "фунт": "GBP",
}

_WHITESPACE_RE = re.compile(r"[\s\u00a0\u202f]+")

def normalize_currency(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    key = stripped.lower().rstrip(".")
    return _CURRENCY_ALIASES.get(key, stripped.upper())

def parse_amount_to_kopecks(s: Optional[str]) -> Optional[int]:
    """'+1 500,00' -> +150000 (пополнение), без '+' -> -150000 (списание)."""
    if not s:
        return None
    
    s = _WHITESPACE_RE.sub("", s.strip())

    if s.startswith("+"):
        sign, s = 1, s[1:]
    elif s.startswith("-"):
        sign, s = -1, s[1:]
    else:
        sign = -1
    s = s.replace(",", ".")
    try:
        return sign * int(Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_balance_to_kopecks(s: Optional[str]) -> Optional[int]:
    """'12 345,67' -> 1234567 (копеек). Знак всегда положительный."""
    if not s:
        return None
    s = _WHITESPACE_RE.sub("", s.strip()).replace(",", ".")
    try:
        return int(Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, ValueError, TypeError):
        return None