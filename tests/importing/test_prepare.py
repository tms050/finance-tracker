"""Тесты на фикстурах, без открытия реальных PDF."""

import hashlib
from datetime import date, datetime, time

import pytest

from src.db.constants import CURRENT_HASH_VERSION
from src.importing.prepare import (
    ERR_CURRENCY_MISMATCH,
    ERR_CURRENCY_NONE_MULTI,
    ERR_MISSING_AMOUNT,
    ERR_MISSING_DATE,
    compute_file_hash,
    compute_file_hash_from_path,
    compute_transaction_hash,
    make_account_key,
    prepare_statement,
    prepare_transaction,
)
from src.parser.sber_parser.models import (
    BalanceCheck,
    ParseResult,
    StatementInfo,
    Transaction as ParsedTransaction,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def make_tx(**kwargs) -> ParsedTransaction:
    defaults = dict(
        date=date(2024, 1, 15),
        time=time(12, 34),
        auth="AUTH123",
        category="Супермаркеты",
        description="Оплата в магазине",
        counterparty_name="PYATEROCHKA",
        currency="RUB",
        amount_raw="-150,00",
        balance_raw="1000,00",
        amount=-15000,
        balance=100000,
    )
    defaults.update(kwargs)
    return ParsedTransaction(**defaults)


def make_result(transactions, **kwargs) -> ParseResult:
    stmt_kwargs = dict(
        currency="RUB",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    stmt_kwargs.update(kwargs.pop("statement_kwargs", {}))
    return ParseResult(
        statement=StatementInfo(**stmt_kwargs),
        transactions=list(transactions),
        balance_check=kwargs.pop("balance_check", None),
        warnings=kwargs.pop("warnings", []),
    )


def hash_tx(**overrides) -> tuple[str, int]:
    """Хэш по полям с эталоном E1."""
    base = dict(
        account_key=make_account_key(1),
        date=date(2024, 1, 15),
        time=time(12, 34),
        amount=-15000,
        currency="RUB",
        description="Оплата в магазине",
        counterparty_name="PYATEROCHKA",
        auth="AUTH123",
    )
    base.update(overrides)
    return compute_transaction_hash(**base)


def prep_tx(**overrides):
    """prepare_transaction по полям с эталоном E1."""
    base = dict(
        account_id=1,
        account_currency="RUB",
        date=date(2024, 1, 15),
        time=time(12, 34),
        amount=-15000,
        currency="RUB",
        description="Оплата в магазине",
        counterparty_name="PYATEROCHKA",
        auth="AUTH123",
        category="Супермаркеты",
    )
    base.update(overrides)
    return prepare_transaction(**base)


# ---------------------------------------------------------------------------
# compute_transaction_hash
# ---------------------------------------------------------------------------

class TestComputeTransactionHash:
    def test_idempotent(self):
        assert hash_tx() == hash_tx()

    def test_none_vs_empty_cp(self):
        assert hash_tx(counterparty_name=None)[0] == hash_tx(counterparty_name="")[0]

    def test_none_vs_empty_desc(self):
        assert hash_tx(description=None)[0] == hash_tx(description="")[0]
        assert hash_tx(description="   ")[0] == hash_tx(description="")[0]

    def test_none_vs_empty_auth(self):
        assert hash_tx(auth=None)[0] == hash_tx(auth="")[0]
        assert hash_tx(auth="   ")[0] == hash_tx(auth="")[0]

    def test_trailing_leading_spaces_description(self):
        h = hash_tx(description="Оплата")[0]
        assert h == hash_tx(description="  Оплата  ")[0]
        assert h == hash_tx(description="\tОплата\n")[0]

    def test_auth_different_hash_different(self):
        assert hash_tx(auth="A1")[0] != hash_tx(auth="A2")[0]

    def test_auth_absent_both_same(self):
        assert hash_tx(auth="")[0] == hash_tx(auth="")[0]

    def test_amount_differs(self):
        assert hash_tx(amount=-15000)[0] != hash_tx(amount=-16000)[0]

    def test_account_key_different(self):
        h1 = compute_transaction_hash(
            account_key=make_account_key(1), date=date(2024, 1, 15),
            time=time(12, 34), amount=-15000, currency="RUB",
            description="x", counterparty_name="y", auth="z",
        )[0]
        h2 = compute_transaction_hash(
            account_key=make_account_key(2), date=date(2024, 1, 15),
            time=time(12, 34), amount=-15000, currency="RUB",
            description="x", counterparty_name="y", auth="z",
        )[0]
        assert h1 != h2

    def test_business_account_key_differs_from_id(self):
        h_id = hash_tx(account_key="1")[0]
        h_bank = hash_tx(account_key="bank:sber:****1234")[0]
        assert h_id != h_bank

    def test_version_different(self):
        h1, v1 = hash_tx(version=1)
        h2, v2 = hash_tx(version=2)
        assert h1 != h2
        assert (v1, v2) == (1, 2)

    def test_default_version(self):
        _, v = hash_tx()
        assert v == CURRENT_HASH_VERSION

    def test_empty_account_key_raises(self):
        with pytest.raises(ValueError):
            compute_transaction_hash(account_key="")

    def test_pipe_in_fields_no_false_collision(self):
        a = hash_tx(description="a|b", counterparty_name="c")[0]
        b = hash_tx(description="a", counterparty_name="b|c")[0]
        assert a != b

    def test_datetime_date_normalized(self):
        assert (
            hash_tx(date=date(2024, 1, 15))[0]
            == hash_tx(date=datetime(2024, 1, 15, 23, 59))[0]
        )

    # ---- новые тесты под _to_date / _to_time с типизацией ----

    def test_date_str_iso(self):
        assert hash_tx(date="2024-01-15")[0] == hash_tx(date=date(2024, 1, 15))[0]

    def test_date_str_dd_mm_yyyy(self):
        assert hash_tx(date="15.01.2024")[0] == hash_tx(date=date(2024, 1, 15))[0]

    def test_date_str_invalid(self):
        # невалидная строка → None → хэш как у пустой даты
        assert hash_tx(date="not-a-date")[0] == hash_tx(date=None)[0]

    def test_time_str_iso(self):
        assert hash_tx(time="12:34")[0] == hash_tx(time=time(12, 34))[0]

    def test_time_str_with_seconds_ignored(self):
        assert hash_tx(time="12:34:45")[0] == hash_tx(time=time(12, 34))[0]


# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------

class TestComputeFileHash:
    def test_bytes_same(self):
        assert compute_file_hash(b"hello world") == hashlib.sha256(b"hello world").hexdigest()

    def test_bytes_different(self):
        assert compute_file_hash(b"a") != compute_file_hash(b"b")

    def test_path_same(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"content")
        assert compute_file_hash_from_path(str(p)) == compute_file_hash(b"content")

    def test_path_different(self, tmp_path):
        p1, p2 = tmp_path / "a.bin", tmp_path / "b.bin"
        p1.write_bytes(b"a")
        p2.write_bytes(b"b")
        assert compute_file_hash_from_path(str(p1)) != compute_file_hash_from_path(str(p2))

    def test_path_large_file(self, tmp_path):
        p = tmp_path / "large.bin"
        data = b"x" * 20000
        p.write_bytes(data)
        assert compute_file_hash_from_path(str(p)) == compute_file_hash(data)


# ---------------------------------------------------------------------------
# prepare_transaction
# ---------------------------------------------------------------------------

class TestPrepareTransaction:
    def test_auth_empty_to_none(self):
        assert prep_tx(auth="").authorization_code is None

    def test_auth_whitespace_to_none(self):
        assert prep_tx(auth="   ").authorization_code is None

    def test_auth_present(self):
        assert prep_tx(auth="A1").authorization_code == "A1"

    def test_currency_none_rub(self):
        p = prep_tx(currency=None, account_currency="RUB")
        assert p.is_valid and p.currency == "RUB"

    def test_currency_none_multi(self):
        p = prep_tx(currency=None, account_currency="MULTI")
        assert not p.is_valid
        assert ERR_CURRENCY_NONE_MULTI in p.validation_errors

    def test_currency_mismatch(self):
        p = prep_tx(currency="USD", account_currency="RUB")
        assert not p.is_valid
        assert ERR_CURRENCY_MISMATCH in p.validation_errors

    def test_currency_match_multi(self):
        assert prep_tx(currency="USD", account_currency="MULTI").is_valid

    def test_date_none(self):
        p = prep_tx(date=None)
        assert not p.is_valid and ERR_MISSING_DATE in p.validation_errors

    def test_amount_none(self):
        p = prep_tx(amount=None)
        assert not p.is_valid and ERR_MISSING_AMOUNT in p.validation_errors

    def test_multiple_errors(self):
        p = prep_tx(date=None, amount=None)
        assert ERR_MISSING_DATE in p.validation_errors
        assert ERR_MISSING_AMOUNT in p.validation_errors

    def test_raw_category(self):
        assert prep_tx(category="Еда").raw_category == "Еда"

    def test_raw_category_empty(self):
        assert prep_tx(category="").raw_category is None

    def test_source_and_version(self):
        p = prep_tx()
        assert p.source == "pdf"
        assert p.hash_version == CURRENT_HASH_VERSION

    def test_is_transfer_false(self):
        assert prep_tx().is_transfer is False

    def test_account_id_none_raises(self):
        with pytest.raises(ValueError):
            prep_tx(account_id=None)

    def test_account_key_overrides_id(self):
        p1 = prep_tx(account_id=1)
        p2 = prep_tx(account_id=1, account_key="bank:sber:****1234")
        assert p1.transaction_hash != p2.transaction_hash

    def test_duck_typing_no_parser_object(self):
        # вызывается без ParsedTransaction - чистые поля
        p = prepare_transaction(
            account_id=42,
            account_currency="RUB",
            date=date(2024, 5, 1),
            amount=12345,
            description="test",
        )
        assert p.is_valid
        assert p.account_id == 42


# ---------------------------------------------------------------------------
# prepare_statement
# ---------------------------------------------------------------------------

class TestPrepareStatement:
    def _path(self, tmp_path) -> str:
        p = tmp_path / "statement.pdf"
        p.write_bytes(b"fake pdf content")
        return str(p)

    def test_all_valid(self, tmp_path):
        result = make_result([make_tx(), make_tx(auth="X1")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert len(prepared.transactions_to_insert) == 2
        assert prepared.rejected == ()
        assert prepared.intra_batch_collisions == ()

    def test_some_invalid(self, tmp_path):
        result = make_result([make_tx(), make_tx(date=None), make_tx(amount=None)])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert len(prepared.transactions_to_insert) == 1
        assert len(prepared.rejected) == 2

    def test_collision_detected(self, tmp_path):
        result = make_result([make_tx(), make_tx()])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert len(prepared.transactions_to_insert) == 2
        assert len(prepared.intra_batch_collisions) == 1
        assert len(prepared.intra_batch_collisions[0].transactions) == 2

    def test_no_collision_when_auth_differs(self, tmp_path):
        result = make_result([make_tx(auth="A"), make_tx(auth="B")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert prepared.intra_batch_collisions == ()

    def test_collision_only_valid(self, tmp_path):
        result = make_result([make_tx(date=None), make_tx(date=None)])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert prepared.transactions_to_insert == ()
        assert len(prepared.rejected) == 2
        assert prepared.intra_batch_collisions == ()

    def test_file_hash_stable(self, tmp_path):
        p = self._path(tmp_path)
        result = make_result([make_tx()])
        p1 = prepare_statement(result, 1, "RUB", p)
        p2 = prepare_statement(result, 1, "RUB", p)
        assert p1.file_hash == p2.file_hash == compute_file_hash(b"fake pdf content")

    def test_file_name_basename(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        p = sub / "file.pdf"
        p.write_bytes(b"x")
        prepared = prepare_statement(make_result([make_tx()]), 1, "RUB", str(p))
        assert prepared.file_name == "file.pdf"

    def test_period_passed_through(self, tmp_path):
        result = make_result(
            [make_tx()],
            statement_kwargs={
                "period_start": date(2024, 2, 1),
                "period_end": date(2024, 2, 29),
            },
        )
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert prepared.period_start == date(2024, 2, 1)
        assert prepared.period_end == date(2024, 2, 29)

    def test_result_warnings_passed(self, tmp_path):
        result = make_result([make_tx()], warnings=["parser warn 1", "parser warn 2"])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert "parser warn 1" in prepared.warnings
        assert "parser warn 2" in prepared.warnings

    def test_extra_warning_l1(self, tmp_path):
        result = make_result(
            [make_tx(currency="USD")],
            statement_kwargs={"currency": "USD"},
        )
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert any("USD" in w and "RUB" in w for w in prepared.warnings)

    def test_extra_warning_l2_aggregate(self, tmp_path):
        result = make_result([make_tx(currency="USD"), make_tx(currency="EUR")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert any("Отклонено" in w and "2" in w for w in prepared.warnings)

    def test_no_auth_warning_no_collisions(self, tmp_path):
        result = make_result([make_tx(auth=""), make_tx(auth="A")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        # базовое сообщение: есть, число корректное (одна tx без auth)
        assert any("без кода авторизации: 1" in w for w in prepared.warnings)
        # усиленного сообщения нет - коллизий не было
        assert not any("различить такие операции по хэшу невозможно" in w
                       for w in prepared.warnings)

    def test_no_auth_warning_with_collisions(self, tmp_path):
        # две одинаковые tx без auth → коллизия + усиленное предупреждение
        result = make_result([make_tx(auth=""), make_tx(auth="")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert len(prepared.intra_batch_collisions) == 1
        assert any("различить такие операции по хэшу невозможно" in w
                   for w in prepared.warnings)

    def test_raw_statement_info_passed(self, tmp_path):
        result = make_result([make_tx()])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert prepared._raw_statement_info is result.statement

    def test_balance_check_passed(self, tmp_path):
        bc = BalanceCheck()
        result = make_result([make_tx()], balance_check=bc)
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert prepared.balance_check is bc

    def test_original_index_preserved(self, tmp_path):
        result = make_result([make_tx(), make_tx(date=None), make_tx(auth="X")])
        prepared = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert sorted(p.original_index for p in prepared.transactions_to_insert) == [0, 2]
        assert prepared.rejected[0].original_index == 1

    def test_account_id_none_raises(self, tmp_path):
        with pytest.raises(ValueError):
            prepare_statement(make_result([make_tx()]), None, "RUB", self._path(tmp_path))

    def test_account_key_flows_through(self, tmp_path):
        result = make_result([make_tx()])
        p1 = prepare_statement(result, 1, "RUB", self._path(tmp_path),
                               account_key="bank:sber:****1234")
        # тот же account_id, но другой account_key → другой хэш
        p2 = prepare_statement(result, 1, "RUB", self._path(tmp_path))
        assert p1.transactions_to_insert[0].transaction_hash != \
               p2.transactions_to_insert[0].transaction_hash