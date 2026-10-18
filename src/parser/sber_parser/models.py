"""Структуры данных результата парсинга. Универсальны для любого банка."""
from dataclasses import dataclass, field, asdict
from datetime import date, time
from typing import Optional
from enum import Enum

from .amount import normalize_currency


@dataclass(slots=True)
class StatementInfo:
    fio: Optional[str] = None
    account_number_masked: Optional[str] = None
    card_number_masked: Optional[str] = None
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    open_date: Optional[date] = None
    close_date: Optional[date] = None

    def __post_init__(self) -> None:
        self.fio = self.fio.strip() if self.fio else None
        self.account_number_masked = self.account_number_masked.strip() if self.account_number_masked else None
        self.card_number_masked = self.card_number_masked.strip() if self.card_number_masked else None
        self.currency = normalize_currency(self.currency)

        if (self.period_start is not None and self.period_end is not None
                and self.period_start > self.period_end):
            raise ValueError(
                f"period_start ({self.period_start}) > period_end ({self.period_end})"
            )
        if (self.open_date is not None and self.close_date is not None
                and self.open_date > self.close_date):
            raise ValueError(
                f"open_date ({self.open_date}) > close_date ({self.close_date})"
            )

    def to_dict(self) -> dict:
        return {
            "fio": self.fio,
            "account_number_masked": self.account_number_masked,
            "card_number_masked": self.card_number_masked,
            "currency": self.currency,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "open_date": self.open_date.isoformat() if self.open_date else None,
            "close_date": self.close_date.isoformat() if self.close_date else None,
        }


@dataclass(slots=True)
class Transaction:
    date: Optional[date] = None
    time: Optional[time] = None
    auth: Optional[str] = None
    category: str = ""
    description: str = ""
    counterparty_name: Optional[str] = None
    currency: str = None
    amount_raw: str = ""
    balance_raw: str = ""
    amount: Optional[int] = None
    balance: Optional[int] = None

    def __post_init__(self) -> None:
        self.category = (self.category or "").strip()
        self.description = (self.description or "").strip()
        self.currency = normalize_currency(self.currency)
        self.amount_raw = (self.amount_raw or "").strip()
        self.balance_raw = (self.balance_raw or "").strip()
        self.auth = (self.auth or "").strip() or None
        if self.counterparty_name is not None:
            cleaned = self.counterparty_name.strip()
            self.counterparty_name = cleaned or None

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "time": self.time.strftime("%H:%M") if self.time else None,
            "auth": self.auth,
            "category": self.category,
            "description": self.description,
            "counterparty_name": self.counterparty_name,
            "currency": self.currency,
            "amount_raw": self.amount_raw,
            "balance_raw": self.balance_raw,
            "amount": self.amount,
            "balance": self.balance,
        }

class BalanceStatus(str, Enum):
    OK                = "ok"
    MISMATCH          = "mismatch"           # суммы не сошлись
    INCOMPLETE        = "incomplete"         # часть записей пропущена
    INSUFFICIENT_DATA = "insufficient_data"  # < 2 валидных записей

@dataclass(slots=True)
class BalanceCheck:
    ok: bool = False
    status: BalanceStatus = BalanceStatus.INSUFFICIENT_DATA
    reason: Optional[str] = None

    n_records: int = 0
    n_total_records: int = 0
    n_skipped: int = 0

    oldest_balance: Optional[int] = None
    newest_balance: Optional[int] = None
    sum_amounts: Optional[int] = None
    expected_newest: Optional[int] = None
    diff: Optional[int] = None


@dataclass(slots=True)
class ParseResult:
    statement: StatementInfo = field(default_factory=StatementInfo)
    transactions: list[Transaction] = field(default_factory=list)
    balance_check: Optional[BalanceCheck] = None
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.transactions)

    def to_dict(self) -> dict:
        bc = self.balance_check
        bc_dict = None
        if bc:
            bc_dict = asdict(bc)
            bc_dict["status"] = bc.status.value  # явная строка "ok"
        return {
            "statement": self.statement.to_dict(),
            "transactions": [t.to_dict() for t in self.transactions],
            "balance_check": bc_dict,
            "warnings": list(self.warnings),
        }