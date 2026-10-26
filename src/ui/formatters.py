from __future__ import annotations

from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Iterable, Protocol

import calendar

if TYPE_CHECKING:
    import pandas as pd

# Единый символ «нет значения» для всего UI.
EMPTY = "—"

# Цвета для колонки «Сумма».
COLOR_INCOME = "#2e7d32"   # зелёный
COLOR_EXPENSE = "#c62828"  # красный

_THOUSANDS_SEP = "\u00a0"  # NBSP - стандартный разделитель тысяч в RU
_DECIMAL_SEP = ","

_VALIDATION_ERRORS_RU = {
    "missing_date": "нет даты",
    "missing_amount": "нет суммы",
    "currency_none_multi": "не указана валюта (счёт MULTI)",
    "currency_mismatch": "валюта не совпадает со счётом",
}

class _CategoryLike(Protocol):
    category_id: int
    name: str
    parent_category_id: int | None


def format_amount(amount: int | None) -> str:
    """Копейки -> строка с явным знаком, NBSP-разделителем и запятой.

    Примеры: 123456 -> '+1 234,56'; -50 -> '-0,50'; 0 -> '0,00'; None -> '-'.
    Знак расхода - U+2212 (минус), не дефис.
    """
    if amount is None:
        return EMPTY
    if amount == 0:
        return f"0{_DECIMAL_SEP}00"
    sign = "+" if amount > 0 else "\u2212"
    abs_val = abs(amount)
    rubles, kopecks = divmod(abs_val, 100)
    rubles_str = f"{rubles:,}".replace(",", _THOUSANDS_SEP)
    return f"{sign}{rubles_str}{_DECIMAL_SEP}{kopecks:02d}"


def amount_style(amount: int | None) -> str:
    """CSS для колонки «Сумма»: выравнивание вправо + цвет по знаку."""
    base = "text-align: right;"
    if amount is None or amount == 0:
        return base
    color = COLOR_INCOME if amount > 0 else COLOR_EXPENSE
    return f"{base} color: {color}; font-weight: 500;"


def format_date(d: date | None) -> str:
    return EMPTY if d is None else d.strftime("%d.%m.%Y")


def format_time(t: time | None) -> str:
    return EMPTY if t is None else t.strftime("%H:%M")


def format_transfer(value: int | bool | None) -> str:
    if value is None:
        return EMPTY
    return "✅" if value else "❌"


def format_optional_text(text: str | None, max_len: int | None = None) -> str:
    """None/пусто -> EMPTY. Опционально - обрезка с многоточием."""
    if text is None:
        return EMPTY
    stripped = text.strip()
    if not stripped:
        return EMPTY
    if max_len is not None and len(stripped) > max_len:
        stripped = stripped[: max_len - 1] + "…"
    return stripped

def _contains_number(name: str, number: str) -> bool:
    n_digits = "".join(c for c in number if c.isdigit())[-4:]
    if not n_digits:
        return False
    return n_digits in name

def format_account_label(
    bank_name: str | None,
    account_name: str | None,
    account_number_masked: str | None,
    *,
    is_closed: bool = False,
) -> str:

    bank = (bank_name or "").strip()
    name = (account_name or "").strip()
    number = (account_number_masked or "").strip()

    if name:
        name_lower = name.lower()
        has_bank = bool(bank) and bank.lower() in name_lower

        has_number = _contains_number(name, number)

        if has_bank and has_number:
            parts = [name]
        elif has_bank:
            parts = [name] + ([number] if number else [])
        elif has_number:
            parts = ([bank] if bank else []) + [name]
        else:
            parts = ([bank] if bank else []) + [name] + ([number] if number else [])
    else:
        parts = ([bank] if bank else []) + ([number] if number else [])

    label = " · ".join(parts) if parts else "Счёт"
    if is_closed:
        label += " (закрыт)"
    return label


def build_category_labels(categories: Iterable[_CategoryLike]) -> dict[int, str]:
    """category_id -> отображаемое имя с префиксом родителя через ' / '."""
    items = list(categories)
    by_id = {c.category_id: c for c in items}
    labels: dict[int, str] = {}
    for c in items:
        parent = (
            by_id.get(c.parent_category_id)
            if c.parent_category_id is not None
            else None
        )
        labels[c.category_id] = f"{parent.name} / {c.name}" if parent else c.name
    return labels

# =========================================================================
# UI-2: форматтеры для страницы загрузки
# =========================================================================

def format_balance_check(bc) -> tuple[str, str]:
    """BalanceCheck -> (уровень Streamlit, сообщение). Без эмодзи:
    Streamlit сам рисует иконку уровня."""
    if bc is None:
        return ("info", "Сверка баланса недоступна")
    raw = getattr(bc.status, "value", bc.status)
    if raw == "ok":
        return ("success", "Баланс сошёлся")
    if raw == "mismatch":
        if bc.diff is None:
            return ("error", "Баланс не сошёлся (разница не определена)")
        return ("error", f"Баланс не сошёлся: разница {format_amount(bc.diff)}")
    if raw == "incomplete":
        return (
            "warning",
            f"Не удалось сверить баланс для {bc.n_skipped} записей "
            f"(у них нет amount или balance). Транзакции всё равно "
            f"импортируются - сверка баланса лишь информационная.",
        )
    if raw == "insufficient_data":
        return ("info", "Недостаточно данных для сверки")
    return ("info", f"Статус сверки: {raw}")


def format_import_status(
    status: str, *, warnings_count: int = 0,
) -> tuple[str, str]:
    """ImportResult.status -> (уровень Streamlit, сообщение). Без эмодзи."""
    if status == "ok":
        if warnings_count:
            return (
                "warning",
                f"Импорт завершён, {warnings_count} предупреждений",
            )
        return ("success", "Импорт завершён")
    if status == "duplicate_statement":
        return ("error", "Файл уже импортирован ранее")
    if status == "no_valid_transactions":
        return ("warning", "Нет валидных транзакций для импорта")
    return ("info", f"Статус импорта: {status}")

def _format_period(start: date | None, end: date | None) -> str:
    s, e = format_date(start), format_date(end)
    if s == EMPTY and e == EMPTY:
        return EMPTY
    if s == EMPTY:
        return f"по {e}"
    if e == EMPTY:
        return f"с {s}"
    return f"{s} – {e}"

def format_parse_meta(info) -> list[tuple[str, str]]:
    """StatementInfo -> список (label, value) для превью. None -> '-'."""

    return [
        ("ФИО", info.fio or EMPTY),
        ("Счёт", info.account_number_masked or EMPTY),
        ("Карта", info.card_number_masked or EMPTY),
        ("Валюта", info.currency or EMPTY),
        ("Период", _format_period(info.period_start, info.period_end)),
        ("Открыт", format_date(info.open_date)),
        ("Закрыт", format_date(info.close_date)),
    ]


def format_skipped_intra(skip) -> str:
    """#N - номер транзакции в выписке (1-based для пользователя)."""
    return f"#{skip.original_index + 1} · hash {skip.transaction_hash[:12]}…"


def format_skipped_cross(skip) -> str:
    return (
        f"#{skip.original_index + 1} · hash {skip.transaction_hash[:12]}… · "
        f"дубликат tx_id={skip.existing_transaction_id}"
    )

def format_rejected_line(rejected) -> str:
    """Одна строка для _render_rejected. 1-based нумерация."""
    row = format_rejected_row(rejected)
    return (
        f"#{rejected.original_index + 1} · {row['Ошибки']} · "
        f"{row['Дата']} {row['Сумма']} {row['Описание']}"
    )


def format_validation_errors(errors: tuple[str, ...]) -> str:
    if not errors:
        return EMPTY
    return ", ".join(_VALIDATION_ERRORS_RU.get(e, e) for e in errors)

def format_rejected_row(rejected) -> dict[str, str]:
    """PreparedTransaction (rejected) -> строка для отображения."""
    errors_ru = format_validation_errors(rejected.validation_errors)
    return {
        "Дата": format_date(rejected.date),
        "Время": format_time(rejected.time),
        "Сумма": format_amount(rejected.amount),
        "Валюта": rejected.currency or EMPTY,
        "Описание": format_optional_text(rejected.description, max_len=80),
        "Ошибки": format_validation_errors(rejected.validation_errors) or EMPTY,
    }

# =========================================================================
# UI-3: форматтеры для страницы «Статистика»
# =========================================================================

def format_summary_period(
    preset: str, today: "date | None" = None,
) -> tuple["date | None", "date | None"]:
    """Пресет -> (date_from, date_to). None = без ограничения."""
    if today is None:
        today = date.today()
    if preset == "Последние 7 дней":
        return today - timedelta(days=6), today
    if preset == "Последние 30 дней":
        return today - timedelta(days=29), today
    if preset == "Текущий месяц":
        return today.replace(day=1), today
    if preset == "Прошлый месяц":
        last_day_prev = today.replace(day=1) - timedelta(days=1)
        return last_day_prev.replace(day=1), last_day_prev
    if preset == "Прошлый квартал":
        q = (today.month - 1) // 3
        if q == 0:
            year, q = today.year - 1, 4
        else:
            year = today.year
        start_month = 3 * (q - 1) + 1
        end_month = start_month + 2
        end_day = calendar.monthrange(year, end_month)[1]
        return date(year, start_month, 1), date(year, end_month, end_day)
    if preset == "Текущий год":
        return date(today.year, 1, 1), today
    return None, None


def format_metric_pair(count: int, transfer_count: int) -> str:
    """'12 / 3' для st.metric."""
    return f"{count} / {transfer_count}"


def format_amount_for_delta(amount: int | None) -> str:
    """Как format_amount, но с ASCII-минусом: st.metric красит delta
    только по '-' (U+2212 не распознаёт)."""
    if amount is None or amount == 0:
        return "0,00"
    sign = "-" if amount < 0 else "+"
    rubles, kopecks = divmod(abs(amount), 100)
    rubles_str = f"{rubles:,}".replace(",", _THOUSANDS_SEP)
    return f"{sign}{rubles_str}{_DECIMAL_SEP}{kopecks:02d}"


def summarize_changes(
    original_df: "pd.DataFrame | None",
    edited_df: "pd.DataFrame | None",
) -> dict[int, bool]:
    """Сравнить вывод st.data_editor с исходным снимком.

    Матчим по 'ID' (а не по позиции): если Streamlit отсортировал строки
    при отображении - не ошибёмся.

    Если edited_df пуст при непустом original_df - возвращаем {}:
    st.data_editor с num_rows="fixed" не даёт удалить все строки, так что
    это означает «Streamlit вернул пустое» (баг/edge case), а не «все
    переводы сняты». Реагировать как на «все сняты» было бы опасно
    (массовое обновление при сбое UI).
    """
    if original_df is None or edited_df is None:
        return {}
    if original_df.empty or edited_df.empty:
        return {}

    orig_map: dict[int, bool] = {}
    for _, row in original_df.iterrows():
        try:
            tx_id = int(row["ID"])
        except (ValueError, TypeError):
            continue
        orig_map[tx_id] = bool(row["Перевод?"])

    changes: dict[int, bool] = {}
    for _, row in edited_df.iterrows():
        try:
            tx_id = int(row["ID"])
        except (ValueError, TypeError):
            continue
        if tx_id not in orig_map:
            continue
        raw = row["Перевод?"]
        # NaN в CheckboxColumn - маловероятно, но defensive.
        if raw is None or (isinstance(raw, float) and raw != raw):
            continue
        new_val = bool(raw)
        if orig_map[tx_id] != new_val:
            changes[tx_id] = new_val
    return changes

# =========================================================================
# UI-4: форматтеры для страницы «Категории»
# =========================================================================

_CATEGORY_TYPE_LABELS = {
    "income": "Доход",
    "expense": "Расход",
    "transfer": "Перевод",
}


def format_category_type_ru(category_type: str) -> str:
    """'income' -> 'Доход'. Незнакомый тип возвращается as-is."""
    return _CATEGORY_TYPE_LABELS.get(category_type, category_type)


def format_category_parents(
    categories: Iterable[_CategoryLike],
) -> dict[int, str]:
    """{category_id: parent_name_or_dash}. Сироты (parent_id без объекта) -> '-'."""
    items = list(categories)
    by_id = {c.category_id: c for c in items}
    result: dict[int, str] = {}
    for c in items:
        if c.parent_category_id is None:
            result[c.category_id] = EMPTY
        else:
            parent = by_id.get(c.parent_category_id)
            result[c.category_id] = parent.name if parent else EMPTY
    return result

# =========================================================================
# UI-5: форматтеры для ручного добавления
# =========================================================================

def format_amount_input_to_kopecks(
    value: float | int | None, *, is_income: bool,
) -> int:
    """Введённые рубли -> копейки с учётом знака.

    Через Decimal(str(value)) - обходим float-артефакты
    (0.29 * 100 = 28.999... в float). Округление до копеек - ROUND_HALF_UP.
    """
    if value is None:
        return 0
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid amount: {value!r}")
    kopecks = int(d * 100)   # ← вот фикс
    return abs(kopecks) if is_income else -abs(kopecks)