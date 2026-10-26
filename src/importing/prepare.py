"""Подготовка данных из ParseResult к вставке в БД.

Не обращается к БД. Не пишет файлов (только читает PDF в compute_file_hash_from_path).

Публичные функции спроектированы **независимыми от объектов парсера** (duck typing): принимают на вход конкретные поля
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional, Union

from src.db.constants import CURRENT_HASH_VERSION, ERR_CURRENCY_UNSUPPORTED, TRANSACTION_CURRENCIES
from src.parser.sber_parser.models import (
    BalanceCheck,
    ParseResult,
    StatementInfo,
    Transaction as ParsedTransaction,
)

# ---------------------------------------------------------------------------
# Коды validation_errors
# ---------------------------------------------------------------------------

ERR_MISSING_DATE = "missing_date"
ERR_MISSING_AMOUNT = "missing_amount"
ERR_CURRENCY_NONE_MULTI = "currency_none_multi"
ERR_CURRENCY_MISMATCH = "currency_mismatch"

DateLike = Union[date, datetime, str, None]
TimeLike = Union[time, datetime, str, None]


# ---------------------------------------------------------------------------
# Dataclass'ы
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    """Транзакция, готовая к вставке в `transactions`."""

    account_id: int
    statement_id: Optional[int]
    date: Optional[date]
    time: Optional[time]
    amount: Optional[int]
    currency: Optional[str]
    description: str
    counterparty_name: Optional[str]
    category_id: Optional[int]
    authorization_code: Optional[str]
    raw_category: Optional[str]
    is_transfer: bool
    transaction_hash: str
    hash_version: int
    source: str
    original_index: int = -1
    is_valid: bool = True
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntraBatchCollision:
    transaction_hash: str
    transactions: tuple[PreparedTransaction, ...]


@dataclass(frozen=True, slots=True)
class PreparedStatement:
    """Результат `prepare_statement`: всё, что нужно для вставки (без БД)."""

    file_name: str
    file_hash: str
    account_id: int
    period_start: Optional[date]
    period_end: Optional[date]
    transactions_to_insert: tuple[PreparedTransaction, ...]
    rejected: tuple[PreparedTransaction, ...]
    intra_batch_collisions: tuple[IntraBatchCollision, ...]
    warnings: tuple[str, ...]
    balance_check: Optional[BalanceCheck]
    _raw_statement_info: Optional[StatementInfo] = None


# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------

def _norm(s: Optional[str]) -> str:
    """None -> ""; strip; NBSP -> пробел. Внутренние пробелы НЕ трогаем."""
    return (s or "").strip().replace("\u00a0", " ")


def _to_date(v: DateLike) -> Optional[date]:
    """date | datetime | str(ISO или DD.MM.YYYY) | None -> date | None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass
        try:
            return datetime.strptime(s, "%d.%m.%Y").date()
        except ValueError:
            return None
    return None


def _to_time(v: TimeLike) -> Optional[time]:
    """time | datetime | str(HH:MM[:SS]) | None -> time | None.

    Секунды и микросекунды обнуляются: хэш использует %H:%M, а парсер
    гарантирует second=0 (см. src/parser/README.md, parse_time).
    """
    if v is None:
        return None
    if isinstance(v, time):
        return v.replace(second=0, microsecond=0)
    if isinstance(v, datetime):
        return v.time().replace(second=0, microsecond=0)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            t = time.fromisoformat(s)
        except ValueError:
            return None
        return t.replace(second=0, microsecond=0)
    return None


# ---------------------------------------------------------------------------
# Хэши
# ---------------------------------------------------------------------------

def make_account_key(account_id: int) -> str:
    """Дефолтный `account_key` для хэша: `str(account_id)`.

    Для **стабильных хэшей при сбросе БД** передавайте в prepare_statement /
    prepare_transaction бизнес-ключ, например `f"bank:{bank_name}:{account_number_masked}"`.
    """
    return str(account_id)


def compute_transaction_hash(
    *,
    account_key: str,
    date: DateLike = None,
    time: TimeLike = None,
    amount: Optional[int] = None,
    currency: Optional[str] = None,
    description: Optional[str] = None,
    counterparty_name: Optional[str] = None,
    auth: Optional[str] = None,
    version: Optional[int] = None,
) -> tuple[str, int]:
    """Вернуть (sha256_hex, version) по правилу хэша v1.

    Duck typing: принимает поля, не объект ParsedTransaction.
    `account_key` - стабильный идентификатор счёта (см. make_account_key и README).
    `version=None` -> CURRENT_HASH_VERSION (не «замерзает» на моменте импорта).
    """
    if not account_key:
        raise ValueError("account_key must be non-empty")

    ver = CURRENT_HASH_VERSION if version is None else version

    d = _to_date(date)
    t = _to_time(time)

    s_acct = account_key
    s_date = d.isoformat() if d else ""
    s_time = t.strftime("%H:%M") if t else ""
    s_amt = str(amount) if amount is not None else ""
    s_cur = (currency or "").upper()
    s_desc = _norm(description)
    s_cp = _norm(counterparty_name)
    s_auth = _norm(auth)

    payload = "|".join([
        f"v{ver}",
        f"acct:{len(s_acct)}:{s_acct}",
        f"date:{len(s_date)}:{s_date}",
        f"time:{len(s_time)}:{s_time}",
        f"amt:{len(s_amt)}:{s_amt}",
        f"cur:{len(s_cur)}:{s_cur}",
        f"desc:{len(s_desc)}:{s_desc}",
        f"cp:{len(s_cp)}:{s_cp}",
        f"auth:{len(s_auth)}:{s_auth}",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), ver


def compute_file_hash(data: bytes) -> str:
    """SHA-256 от байтов (чистая функция, тестируется без ФС)."""
    return hashlib.sha256(data).hexdigest()


def compute_file_hash_from_path(path: str, chunk_size: int = 8192) -> str:
    """SHA-256 от содержимого файла, читает чанками (не грузит файл целиком)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# prepare_transaction
# ---------------------------------------------------------------------------

def prepare_transaction(
    *,
    account_id: int,
    account_currency: str,
    account_key: Optional[str] = None,
    date: DateLike = None,
    time: TimeLike = None,
    amount: Optional[int] = None,
    currency: Optional[str] = None,
    description: Optional[str] = None,
    counterparty_name: Optional[str] = None,
    auth: Optional[str] = None,
    category: Optional[str] = None,
    original_index: int = -1,
) -> PreparedTransaction:
    """Нормализовать и провалидировать одну транзакцию (duck typing)."""
    if account_id is None:
        raise ValueError("account_id must not be None")

    key = account_key if account_key is not None else make_account_key(account_id)

    errors: list[str] = []

    d = _to_date(date)
    if d is None:
        errors.append(ERR_MISSING_DATE)

    if amount is None:
        errors.append(ERR_MISSING_AMOUNT)

    tx_cur: Optional[str] = (currency or "").upper() or None
    final_currency: Optional[str] = tx_cur

    if tx_cur is None:
        if account_currency == "MULTI":
            errors.append(ERR_CURRENCY_NONE_MULTI)
        else:
            final_currency = account_currency
    else:
        if account_currency != "MULTI" and tx_cur != account_currency:
            errors.append(ERR_CURRENCY_MISMATCH)
    if final_currency is not None and final_currency not in TRANSACTION_CURRENCIES:
        errors.append(ERR_CURRENCY_UNSUPPORTED)
    auth_clean = (auth or "").strip()
    authorization_code: Optional[str] = auth_clean or None
    raw_category = (category or "").strip() or None

    t = _to_time(time)

    s_desc = _norm(description)
    s_cp   = _norm(counterparty_name)
    s_auth = _norm(auth)

    tx_hash, hash_version = compute_transaction_hash(
        account_key=key,
        date=d,
        time=t,
        amount=amount,
        currency=currency,
        description=s_desc,
        counterparty_name=s_cp,
        auth=s_auth,
    )

    return PreparedTransaction(
        account_id=account_id,
        statement_id=None,
        date=d,
        time=t,
        amount=amount,
        currency=final_currency,
        description=s_desc or None,
        counterparty_name=s_cp or None,
        category_id=None,
        authorization_code=authorization_code,
        raw_category=raw_category,
        is_transfer=False,
        transaction_hash=tx_hash,
        hash_version=hash_version,
        source="pdf",
        original_index=original_index,
        is_valid=not errors,
        validation_errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# prepare_statement
# ---------------------------------------------------------------------------

def prepare_statement(
    result: ParseResult,
    account_id: int,
    account_currency: str,
    file_path: str,
    *,
    account_key: Optional[str] = None,
) -> PreparedStatement:
    """ParseResult -> PreparedStatement. БД не трогает."""
    if account_id is None:
        raise ValueError("account_id must not be None")

    file_hash = compute_file_hash_from_path(file_path)
    file_name = os.path.basename(file_path)

    prepared = [
        prepare_transaction(
            account_id=account_id,
            account_currency=account_currency,
            account_key=account_key,
            date=tx.date,
            time=tx.time,
            amount=tx.amount,
            currency=tx.currency,
            description=tx.description,
            counterparty_name=tx.counterparty_name,
            auth=tx.auth,
            category=tx.category,
            original_index=i,
        )
        for i, tx in enumerate(result.transactions)
    ]

    to_insert = tuple(p for p in prepared if p.is_valid)
    rejected = tuple(p for p in prepared if not p.is_valid)

    by_hash: dict[str, list[PreparedTransaction]] = {}
    for p in to_insert:
        by_hash.setdefault(p.transaction_hash, []).append(p)
    collisions = tuple(
        IntraBatchCollision(transaction_hash=h, transactions=tuple(txs))
        for h, txs in by_hash.items()
        if len(txs) >= 2
    )

    # --- warnings ---
    warnings: list[str] = list(result.warnings)

    stmt_cur = result.statement.currency if result.statement else None

    if (
        stmt_cur is not None
        and account_currency != "MULTI"
        and stmt_cur != account_currency
    ):
        warnings.append(
            f"Валюта выписки '{stmt_cur}' не совпадает с валютой счёта "
            f"'{account_currency}'. Проверьте, что загружаете правильную выписку."
        )

    mismatch_count = sum(
        1 for p in rejected if ERR_CURRENCY_MISMATCH in p.validation_errors
    )
    if mismatch_count:
        warnings.append(
            f"Отклонено {mismatch_count} транзакций: валюта не совпадает с "
            f"валютой счёта '{account_currency}'. Пометьте счёт как MULTI, "
            f"если он мультивалютный."
        )

    no_auth_count = sum(1 for p in to_insert if p.authorization_code is None)
    if no_auth_count:
        if collisions:
            collisions_without_auth = sum(
                1 for c in collisions
                if all(p.authorization_code is None for p in c.transactions)
            )
            if collisions_without_auth:
                warnings.append(
                    f"Обнаружено {len(collisions)} групп коллизий, "
                    f"из них {collisions_without_auth} - среди транзакций "
                    f"без кода авторизации (всего без auth: {no_auth_count}). "
                    f"Внимательно проверьте дубликаты: различить такие "
                    f"операции по хэшу невозможно."
                )
            else:
                warnings.append(
                    f"Обнаружено {len(collisions)} групп коллизий; "
                    f"транзакций без кода авторизации: {no_auth_count}. "
                    f"Проверьте дубликаты перед импортом."
                )
        else:
            warnings.append(
                f"Транзакций без кода авторизации: {no_auth_count}. "
                f"Это нормально для некоторых операций, но может привести к "
                f"коллизиям хэшей при повторяющихся транзакциях."
            )

    return PreparedStatement(
        file_name=file_name,
        file_hash=file_hash,
        account_id=account_id,
        period_start=result.statement.period_start if result.statement else None,
        period_end=result.statement.period_end if result.statement else None,
        transactions_to_insert=to_insert,
        rejected=rejected,
        intra_batch_collisions=collisions,
        warnings=tuple(warnings),
        balance_check=result.balance_check,
        _raw_statement_info=result.statement,
    )