"""Чистые тесты без открытия PDF.

Покрывают:
- amount.py / dates.py / counterparty.py;
- dataclass-контракты: ParserConfig / ColumnLayout / StatementInfo / Transaction / BalanceCheck / ParseResult;
- постобработку SberStatementParser._normalize (counterparty_name).
"""
import datetime
import json

import pytest

from src.parser.sber_parser.counterparty import extract_person_name
from src.parser.sber_parser.dates import parse_date, parse_time, DATE_RE, TIME_RE
from src.parser.sber_parser.amount import (
    parse_amount_to_kopecks,
    parse_balance_to_kopecks,
    normalize_currency,
)
from src.parser.sber_parser.config import ParserConfig, ColumnLayout
from src.parser.sber_parser.models import (
    BalanceCheck,
    BalanceStatus,
    ParseResult,
    StatementInfo,
    Transaction,
)


# ============================================================
#  parse_date
# ============================================================

@pytest.mark.parametrize("raw, expected", [
    ("01.03.2024", datetime.date(2024, 3, 1)),
    ("01.10.2026", datetime.date(2026, 10, 1)),
    ("31.12.2026", datetime.date(2026, 12, 31)),
    ("01.01.2000", datetime.date(2000, 1, 1)),
    ("31.01.2024", datetime.date(2024, 1, 31)),
    ("30.04.2024", datetime.date(2024, 4, 30)),
    ("29.02.2024", datetime.date(2024, 2, 29)),
    ("29.02.2000", datetime.date(2000, 2, 29)),
    ("29.02.2023", None),
    ("29.02.1900", None),
    ("29.02.2100", None),
    ("30.02.2024", None),
    ("31.04.2024", None),
    ("00.01.2024", None),
    ("01.00.2024", None),
    ("01.13.2024", None),
    ("32.01.2024", None),
    ("1.3.2024",   None),
    ("01.3.2024",  None),
    ("1.03.2024",  None),
    ("2024-03-01", None),
    ("01/03/2024", None),
    ("01-03-2024", None),
    ("01.03.24",   None),
    ("01.03.2024 ", None),
    ("abc",  None),
    ("",     None),
    (None,   None),
    (datetime.date(2024, 3, 1), datetime.date(2024, 3, 1)),
    (datetime.date(1999, 12, 31), datetime.date(1999, 12, 31)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected

def test_parse_date_accepts_datetime():
    dt = datetime.datetime(2024, 3, 1, 15, 30)
    assert parse_date(dt) == datetime.date(2024, 3, 1)

def test_parse_date_returns_same_object_for_date():
    d = datetime.date(2024, 3, 1)
    assert parse_date(d) is d


# ============================================================
#  parse_time
# ============================================================

@pytest.mark.parametrize("raw, expected", [
    ("10:03", datetime.time(10, 3)),
    ("10:30", datetime.time(10, 30)),
    ("00:00", datetime.time(0, 0)),
    ("23:59", datetime.time(23, 59)),
    ("09:05", datetime.time(9, 5)),
    ("9:05",  None),
    ("09:5",  None),
    ("24:00", None),
    ("25:00", None),
    ("-1:00", None),
    ("10:60", None),
    ("10:99", None),
    ("10-03", None),
    ("10.03", None),
    ("12:34:56", None),
    ("12:34:56.789", None),
    ("1030", None),
    ("abc", None),
    ("", None),
    (None, None),
    (datetime.time(10, 3), datetime.time(10, 3)),
    (datetime.time(23, 59), datetime.time(23, 59)),
])
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected

def test_parse_time_accepts_datetime():
    dt = datetime.datetime(2024, 3, 1, 15, 30, 45)
    assert parse_time(dt) == datetime.time(15, 30)

def test_parse_time_seconds_dropped_from_datetime():
    dt = datetime.datetime(2024, 3, 1, 15, 30, 45)
    assert parse_time(dt).second == 0


# ============================================================
#  parse_amount_to_kopecks
# ============================================================

@pytest.mark.parametrize("raw, expected", [
    ("1 500,00",            -150000),
    ("1 234,56",            -123456),
    ("100,00",              -10000),
    ("1,00",                -100),
    ("0,01",                -1),
    ("0,99",                -99),
    ("+1 500,00",            150000),
    ("+100,00",              10000),
    ("+0,01",                    1),
    ("+1",                   100),
    ("-1 500,00",           -150000),
    ("-100,00",             -10000),
    ("-0,01",                    -1),
    ("1 234",               -123400),
    ("+100",                 10000),
    ("-100",                -10000),
    ("1 234,5",             -123450),
    ("+1 234,5",             123450),
    ("1\u00a0500,00",       -150000),
    ("1\u202f500,00",       -150000),
    ("1 500,00 ",           -150000),
    (" 1 500,00",           -150000),
    ("+ 1 500,00",           150000),
    ("- 1 500,00",          -150000),
    ("1500,00",             -150000),
    ("1500",                -150000),
    ("0",                         0),
    ("0,00",                      0),
    ("+0,00",                     0),
    ("-0,00",                     0),
    ("1,001",                    -100),
    ("1,004",                    -100),
    ("1,005",                    -101),
    ("1,006",                    -101),
    ("1,015",                    -102),
    ("+0,005",                      1),
    ("",      None),
    ("   ",   None),
    ("abc",   None),
    ("+,",    None),
    ("-,",    None),
    ("+",     None),
    ("-",     None),
    (",",     None),
    ("1,2,3", None),
    ("1.5,00", None),
    (None,    None),
])
def test_parse_amount_to_kopecks(raw, expected):
    assert parse_amount_to_kopecks(raw) == expected

def test_parse_amount_returns_int():
    assert isinstance(parse_amount_to_kopecks("1 500,00"), int)
    assert isinstance(parse_amount_to_kopecks("+1 500,00"), int)


# ============================================================
#  parse_balance_to_kopecks
# ============================================================

@pytest.mark.parametrize("raw, expected", [
    ("12 345,67",          1234567),
    ("0,00",                     0),
    ("0",                        0),
    ("1,00",                   100),
    ("100,00",               10000),
    ("1 000 000,00",    100000000),
    ("-500,00",             -50000),
    ("-1 000,00",          -100000),
    ("+100,00",              10000),
    ("\u00a012\u00a0345,67", 1234567),
    (" 12 345,67 ",          1234567),
    ("",     None),
    ("abc",  None),
    (None,   None),
])
def test_parse_balance_to_kopecks(raw, expected):
    assert parse_balance_to_kopecks(raw) == expected


# ============================================================
#  normalize_currency
# ============================================================

@pytest.mark.parametrize("raw, expected", [
    ("₽",        "RUB"),
    ("руб.",     "RUB"),
    ("руб",      "RUB"),
    ("рубль",    "RUB"),
    ("РУБ.",     "RUB"),
    ("RUR",      "RUB"),
    ("rur",      "RUB"),
    ("rub",      "RUB"),
    ("RUB",      "RUB"),
    ("  rub  ",  "RUB"),
    ("$",        "USD"),
    ("USD",      "USD"),
    ("usd",      "USD"),
    ("  usd ",   "USD"),
    ("€",        "EUR"),
    ("EUR",      "EUR"),
    ("eur",      "EUR"),
    ("евро",     "EUR"),
    ("Евро",     "EUR"),
    ("KZT",      "KZT"),
    ("kzt",      "KZT"),
    ("  kzt ",   "KZT"),
    ("GBP",      "GBP"),
    ("CNY",      "CNY"),
    ("  bitcoin  ", "BITCOIN"),
    ("abcd",        "ABCD"),
    (None,       None),
    ("",         None),
    ("   ",      None),
])
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected


# ============================================================
#  ParserConfig
# ============================================================

def test_parser_config_defaults_ok():
    cfg = ParserConfig()
    assert 0.0 < cfg.time_boundary_ratio < 1.0
    assert 0.0 < cfg.header_search_limit <= 1.0
    assert cfg.line_tolerance > 0
    assert cfg.shape_window > 0
    assert cfg.header_anchor_words
    assert cfg.footer_phrases
    assert cfg.header_marker


@pytest.mark.parametrize("value", [
    0.0, 1.0, -0.1, 1.5, -1.0, 2.0, 100.0,
])
def test_parser_config_bad_time_boundary_ratio(value):
    with pytest.raises(ValueError):
        ParserConfig(time_boundary_ratio=value)


@pytest.mark.parametrize("value", [0.0, -0.1, 1.5, -1.0, 2.0])
def test_parser_config_bad_header_search_limit(value):
    with pytest.raises(ValueError):
        ParserConfig(header_search_limit=value)


@pytest.mark.parametrize("field", ["line_tolerance", "shape_window"])
@pytest.mark.parametrize("value", [0, -1, -100, -9999])
def test_parser_config_bad_positive_int(field, value):
    with pytest.raises(ValueError):
        ParserConfig(**{field: value})


@pytest.mark.parametrize("field", ["header_anchor_words", "footer_phrases"])
def test_parser_config_empty_tuple(field):
    with pytest.raises(ValueError):
        ParserConfig(**{field: ()})


@pytest.mark.parametrize("value", ["", "   "])
def test_parser_config_empty_header_marker(value):
    with pytest.raises(ValueError):
        ParserConfig(header_marker=value)


@pytest.mark.parametrize("field, value", [
    ("line_tolerance", 1),
    ("line_tolerance", 5),
    ("line_tolerance", 100),
    ("shape_window", 1),
    ("shape_window", 200),
    ("header_marker", "код"),
    ("time_boundary_ratio", 0.5),
    ("header_search_limit", 0.9),
])
def test_parser_config_valid_overrides(field, value):
    cfg = ParserConfig(**{field: value})
    assert getattr(cfg, field) == value


# ============================================================
#  ColumnLayout
# ============================================================

def _valid_layout_kwargs():
    return dict(
        date=(10.0, 50.0),
        time=(50.0, 90.0),
        category=(90.0, 200.0),
        amount=(200.0, 300.0),
        balance=(300.0, 400.0),
    )


def test_column_layout_from_tuples_normalizes():
    layout = ColumnLayout(**_valid_layout_kwargs())
    assert layout.date.x0 == 10.0
    assert layout.date.x1 == 50.0
    assert layout.balance.x1 == 400.0


@pytest.mark.parametrize("shift", [0.0, 1.0, 100.0, 1000.0])
def test_column_layout_from_tuples_with_offset(shift):
    kwargs = {k: (v[0] + shift, v[1] + shift)
              for k, v in _valid_layout_kwargs().items()}
    layout = ColumnLayout(**kwargs)
    assert layout.date.x0 == 10.0 + shift


def test_column_layout_default_ok():
    layout = ColumnLayout.default()
    cols = [layout.date, layout.time, layout.category, layout.amount, layout.balance]
    for col in cols:
        assert col.x0 < col.x1
    for prev, nxt in zip(cols, cols[1:]):
        assert prev.x1 <= nxt.x0


def test_column_layout_rejects_reversed_interval():
    kwargs = _valid_layout_kwargs()
    kwargs["date"] = (50.0, 10.0)
    with pytest.raises(ValueError):
        ColumnLayout(**kwargs)


def test_column_layout_rejects_equal_bounds():
    kwargs = _valid_layout_kwargs()
    kwargs["date"] = (10.0, 10.0)
    with pytest.raises(ValueError):
        ColumnLayout(**kwargs)


def test_column_layout_rejects_overlap():
    kwargs = _valid_layout_kwargs()
    kwargs["time"] = (40.0, 90.0)
    with pytest.raises(ValueError):
        ColumnLayout(**kwargs)


def test_column_layout_rejects_out_of_order():
    kwargs = _valid_layout_kwargs()
    kwargs["amount"] = (300.0, 400.0)
    kwargs["balance"] = (200.0, 300.0)
    with pytest.raises(ValueError):
        ColumnLayout(**kwargs)


def test_column_layout_to_dict_structure():
    d = ColumnLayout.default().to_dict()
    assert set(d.keys()) == {"date", "time", "category", "amount", "balance"}
    for v in d.values():
        assert set(v.keys()) == {"x0", "x1"}
        assert isinstance(v["x0"], float)
        assert isinstance(v["x1"], float)


def test_column_layout_to_dict_roundtrip():
    layout = ColumnLayout.default()
    d = layout.to_dict()
    layout2 = ColumnLayout.from_dict(d)
    assert layout2.to_dict() == d


def test_column_layout_from_dict_rejects_overlap():
    d = ColumnLayout.default().to_dict()
    d["time"]["x0"] = d["date"]["x0"]
    with pytest.raises(ValueError):
        ColumnLayout.from_dict(d)


# ============================================================
#  StatementInfo
# ============================================================

def test_statement_info_defaults_ok():
    info = StatementInfo()
    assert info.fio is None
    assert info.account_number_masked is None
    assert info.card_number_masked is None
    assert info.currency is None
    assert info.period_start is None
    assert info.period_end is None
    assert info.open_date is None
    assert info.close_date is None


@pytest.mark.parametrize("raw, expected", [
    ("₽",    "RUB"),
    ("rub",  "RUB"),
    ("RUR",  "RUB"),
    ("$",    "USD"),
    ("USD",  "USD"),
    ("€",    "EUR"),
    ("",     None),
    (None,   None),
])
def test_statement_info_currency_normalized(raw, expected):
    assert StatementInfo(currency=raw).currency == expected


def test_statement_info_period_order_enforced():
    with pytest.raises(ValueError):
        StatementInfo(
            period_start=datetime.date(2024, 12, 1),
            period_end=datetime.date(2024, 1, 1),
        )


def test_statement_info_open_close_order_enforced():
    with pytest.raises(ValueError):
        StatementInfo(
            open_date=datetime.date(2024, 12, 1),
            close_date=datetime.date(2024, 1, 1),
        )


def test_statement_info_equal_dates_ok():
    d = datetime.date(2024, 3, 1)
    StatementInfo(period_start=d, period_end=d)
    StatementInfo(open_date=d, close_date=d)


def test_statement_info_one_sided_dates_ok():
    StatementInfo(period_start=datetime.date(2024, 1, 1))
    StatementInfo(period_end=datetime.date(2024, 1, 31))


def test_statement_info_to_dict_iso_and_jsonable():
    info = StatementInfo(
        fio="Иванов И.И.",
        account_number_masked="**** 1234",
        card_number_masked="**** 5678",
        currency="₽",
        period_start=datetime.date(2024, 1, 1),
        period_end=datetime.date(2024, 1, 31),
        open_date=datetime.date(2023, 12, 1),
    )
    d = info.to_dict()
    assert d["period_start"] == "2024-01-01"
    assert d["period_end"] == "2024-01-31"
    assert d["open_date"] == "2023-12-01"
    assert d["close_date"] is None
    assert d["currency"] == "RUB"
    json.dumps(d, ensure_ascii=False)


def test_statement_info_to_dict_none_dates():
    d = StatementInfo().to_dict()
    for key in ("period_start", "period_end", "open_date", "close_date"):
        assert d[key] is None


# ============================================================
#  Transaction
# ============================================================

def test_transaction_defaults():
    tx = Transaction()
    assert tx.date is None
    assert tx.time is None
    assert tx.auth is None
    assert tx.category == ""
    assert tx.description == ""
    assert tx.counterparty_name is None
    assert tx.currency is None
    assert tx.amount_raw == ""
    assert tx.balance_raw == ""
    assert tx.amount is None
    assert tx.balance is None


@pytest.mark.parametrize("field", [
    "auth", "category", "description", "amount_raw", "balance_raw",
])
def test_transaction_strips_strings(field):
    tx = Transaction(**{field: "  value  "})
    assert getattr(tx, field) == "value"


@pytest.mark.parametrize("raw, expected", [
    ("  rub  ", "RUB"),
    ("₽",       "RUB"),
    ("USD",     "USD"),
    ("  ",      None),
    ("",        None),
    (None,      None),
])
def test_transaction_currency_normalized(raw, expected):
    tx = Transaction(currency=raw)
    assert tx.currency == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\t", None])
def test_transaction_blank_counterparty_becomes_none(raw):
    assert Transaction(counterparty_name=raw).counterparty_name is None


@pytest.mark.parametrize("raw, expected", [
    ("  Иванов И.И.  ", "Иванов И.И."),
    ("Sberbank",        "Sberbank"),
    ("ООО Ромашка",     "ООО Ромашка"),
])
def test_transaction_counterparty_kept(raw, expected):
    assert Transaction(counterparty_name=raw).counterparty_name == expected


def test_transaction_to_dict_full():
    tx = Transaction(
        date=datetime.date(2024, 3, 1),
        time=datetime.time(10, 30),
        auth="AUTH",
        category="food",
        description="test",
        counterparty_name="Shop",
        currency="rub",
        amount_raw="+1 500,00",
        balance_raw="12 345,67",
        amount=150000,
        balance=1234567,
    )
    d = tx.to_dict()
    assert d["date"] == "2024-03-01"
    assert d["time"] == "10:30"
    assert d["currency"] == "RUB"
    assert d["amount"] == 150000
    assert d["balance"] == 1234567
    assert d["amount_raw"] == "+1 500,00"
    assert d["balance_raw"] == "12 345,67"
    json.dumps(d, ensure_ascii=False)


def test_transaction_to_dict_handles_none_dt():
    d = Transaction().to_dict()
    assert d["date"] is None
    assert d["time"] is None
    json.dumps(d, ensure_ascii=False)


# ============================================================
#  BalanceCheck / BalanceStatus
# ============================================================

def test_balance_status_is_str_enum():
    for member in BalanceStatus:
        assert isinstance(member.value, str)


def test_balance_status_members_present():
    assert BalanceStatus.OK.value == "ok"
    assert BalanceStatus.MISMATCH.value == "mismatch"
    assert BalanceStatus.INCOMPLETE.value == "incomplete"
    assert BalanceStatus.INSUFFICIENT_DATA.value == "insufficient_data"


def test_balance_check_defaults():
    check = BalanceCheck()
    assert check.ok is False
    assert check.status == BalanceStatus.INSUFFICIENT_DATA
    assert check.reason is None
    assert check.n_records == 0
    assert check.n_total_records == 0
    assert check.n_skipped == 0
    assert check.oldest_balance is None
    assert check.newest_balance is None
    assert check.sum_amounts is None
    assert check.expected_newest is None
    assert check.diff is None


def test_balance_check_ok_true_with_status_ok():
    check = BalanceCheck(
        ok=True,
        status=BalanceStatus.OK,
        n_records=10,
        n_total_records=10,
        n_skipped=0,
        oldest_balance=1000,
        newest_balance=5000,
        sum_amounts=4000,
        expected_newest=5000,
        diff=0,
    )
    assert check.ok is True
    assert check.status == BalanceStatus.OK
    assert check.diff == 0
    assert check.n_skipped == 0


@pytest.mark.parametrize("status", [
    BalanceStatus.MISMATCH,
    BalanceStatus.INCOMPLETE,
    BalanceStatus.INSUFFICIENT_DATA,
])
def test_balance_check_ok_false_for_non_ok(status):
    check = BalanceCheck(ok=False, status=status, reason="x")
    assert check.ok is False
    assert check.status is status


# ============================================================
#  ParseResult
# ============================================================

def test_parse_result_empty_len_zero():
    result = ParseResult(statement=StatementInfo())
    assert len(result) == 0


def test_parse_result_len_counts_transactions():
    result = ParseResult(
        statement=StatementInfo(),
        transactions=[Transaction(), Transaction(), Transaction()],
    )
    assert len(result) == 3


def test_parse_result_warnings_isolated_between_instances():
    r1 = ParseResult(statement=StatementInfo())
    r2 = ParseResult(statement=StatementInfo())
    r1.warnings.append("x")
    assert r2.warnings == []
    assert r1.warnings == ["x"]


def test_parse_result_to_dict_json_serializable():
    result = ParseResult(
        statement=StatementInfo(
            period_start=datetime.date(2024, 1, 1),
            period_end=datetime.date(2024, 1, 31),
            currency="₽",
        ),
        transactions=[
            Transaction(
                date=datetime.date(2024, 1, 5),
                time=datetime.time(12, 30),
                amount=-100,
                balance=1000,
                currency="rub",
            ),
            Transaction(
                date=datetime.date(2024, 1, 6),
                time=datetime.time(9, 5),
                amount=500,
                balance=1500,
                currency="rub",
            ),
        ],
        balance_check=BalanceCheck(
            ok=True, status=BalanceStatus.OK, diff=0,
            n_records=2, n_total_records=2, n_skipped=0,
        ),
        warnings=["footer не найден"],
    )
    d = result.to_dict()

    assert d["statement"]["period_start"] == "2024-01-01"
    assert d["statement"]["currency"] == "RUB"
    assert d["balance_check"]["status"] == "ok"
    assert isinstance(d["balance_check"]["status"], str)
    assert d["transactions"][0]["date"] == "2024-01-05"
    assert d["transactions"][0]["time"] == "12:30"
    assert d["warnings"] == ["footer не найден"]

    json.dumps(d, ensure_ascii=False)


def test_parse_result_to_dict_empty():
    d = ParseResult(statement=StatementInfo()).to_dict()
    json.dumps(d, ensure_ascii=False)
    assert d["transactions"] == []


# ============================================================
#  counterparty_name (через _normalize)
# ============================================================

@pytest.mark.parametrize("description, expected", [
    ("VODA MOSKVA RUS.",                       "VODA MOSKVA RUS"),
    ("VODA MOSKVA RUS. Оплата товаров",        "VODA MOSKVA RUS"),
    ("SBOL.",                                  "SBOL"),
    ("KHLEB DA SOL. Покупка",                  "KHLEB DA SOL"),
    ("Банкомат №123.",                         "Банкомат №123"),
    ("Оплата связи. МТС",                      "Оплата связи"),
    ("MAGAZIN 24.",                            "MAGAZIN 24"),
    ("Coffee Point. Услуги",                   "Coffee Point"),
    ("OOO ROMASHKA. Оплата",                   "OOO ROMASHKA"),
    ("Перевод в Сбербанк.",                    "Перевод в Сбербанк"),
    ("Перевод в Тинькофф Банк.",               "Перевод в Тинькофф Банк"),
    ("Перевод в ВТБ.",                         "Перевод в ВТБ"),
    ("Перевод в Альфа-Банк.",                  "Перевод в Альфа-Банк"),
    ("Перевод от И. Иван Иванов. Операция...", "И. Иван Иванов"),
    ("Перевод для П. Пётр Петров.",            "П. Пётр Петров"),
    ("Перевод от Иванов Иван Иванович.",       "Иванов Иван Иванович"),
    ("Перевод от ООО Ромашка.",                "ООО Ромашка"),
    ("Перевод для ООО Ромашка. Услуги",        "ООО Ромашка"),
    ("Перевод от Смирнов А.А.",                "Смирнов А.А."),
    ("Перевод для Кузнецова М.",               "Кузнецова М."),
    ("Что-то без точки",                       None),
    ("",                                       None),
    (None,                                     None),
])
def test_counterparty_name(parser, description, expected):
    tx = Transaction(description=description or "")
    tx = parser._normalize(tx, currency="RUB")
    assert tx.counterparty_name == expected


def test_normalize_fills_currency_on_transaction(parser):
    tx = Transaction(description="SBOL.")
    tx = parser._normalize(tx, currency="rub")
    assert tx.currency == "RUB"