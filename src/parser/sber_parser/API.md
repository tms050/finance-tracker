# API: чёрный ящик

Справочник по публичному API пакета `sber_parser`. Для каждого класса описан **контракт**: что принимается, что возвращается, что гарантируется, чего делать не стоит.

Внутренности (`_parse_page`, `_split_into_records`, работа с `pdfplumber`) намеренно опущены - они не являются частью контракта и могут меняться.

---

## Содержание

- [`parse_data`](#parse_data)
  - [`parse_date`](#parse_date)
  - [`parse_time`](#parse_time)
  - [`parse_amount_to_kopecks`](#parse_amount_to_kopecks)
  - [`parse_balance_to_kopecks`](#parse_balance_to_kopecks)
  - [`normalize_currency`](#normalize_currency)
- [`ParserConfig`](#parserconfig)
- [`ColumnLayout`](#columnlayout)
- [`StatementInfo`](#statementinfo)
- [`Transaction`](#transaction)
- [`BalanceCheck`](#balancecheck)
- [`ParseResult`](#parseresult)
- [`SberStatementParser`](#sberstatementparser)
- [Памятка: как ветвиться по результату](#памятка-как-ветвиться-по-результату)

---

## `money`

Модуль чистых функций: никаких побочных эффектов, никаких исключений на «плохих» данных - только `None`.

### `parse_date`

```python
parse_date(s: Union[str, date, datetime, None]) -> Optional[date]
```

Приводит значение к `datetime.date`.

| Вход | Выход |
|---|---|
| `None` | `None` |
| `date` | тот же объект (идемпотентно) |
| `datetime` | `.date()` |
| `"01.10.2026"` | `date(2026, 10, 1)` |
| `"2026-10-01"`, `"01/10/2026"`, `"мусор"` | `None` |
| `"32.13.2026"` | `None` |

**Гарантии.** Формат строго `DD.MM.YYYY`. Никогда не бросает.

### `parse_time`

```python
parse_time(s: Union[str, time, datetime, None]) -> Optional[time]
```

Приводит значение к `datetime.time`.

| Вход | Выход |
|---|---|
| `None` | `None` |
| `time` | тот же объект |
| `datetime` | `time(h, m)` - **секунды отбрасываются** |
| `"12:34"` | `time(12, 34)` |
| `"25:00"`, `"12:34:56"`, `"abc"` | `None` |

**Гарантии.** Только `HH:MM`. Секунды (`microsecond`, `second`) всегда `0`. Никогда не бросает.

### `parse_amount_to_kopecks`

```python
parse_amount_to_kopecks(s: Optional[str]) -> Optional[int]
```

Превращает строку вида `"+1 500,00"` в целое число копеек.

- Префикс `+` -> знак `+1` (пополнение).
- Префикс `-` **или его отсутствие** -> знак `-1` (списание).
- Разделители разрядов: обычный пробел, NBSP (`\u00a0`), узкий NBSP (`\u202f`), запятая как десятичный разделитель.
- Округление - `ROUND_HALF_UP` до копеек.
- Невалидный вход, `None`, пустая строка -> `None`. Никогда не бросает.

**Примеры:**

| Вход | Выход |
|---|---|
| `"+1 500,00"` | `+150000` |
| `"+1\u202f500,00"` | `+150000` |
| `"1 500,00"` | `-150000` |
| `"-1 500,00"` | `-150000` |
| `"0,00"` | `0` |
| `"1,005"` | `-101` (HALF_UP до копеек; знак по умолчанию - минус) |

> **Внимание на знак по умолчанию.** «Нет префикса = списание» - это
> правило Сбера. Для другого банка семантика может отличаться -
> нормализуйте знак самостоятельно перед вызовом.

### `parse_balance_to_kopecks`

```python
parse_balance_to_kopecks(s: Optional[str]) -> Optional[int]
```

То же, что `parse_amount_to_kopecks`, но **знак всегда неотрицательный**: баланс - это остаток, а не операция.

### `normalize_currency`

```python
normalize_currency(raw: Optional[str]) -> Optional[str]
```

Приводит валюту к ISO 4217.

| Вход | Выход |
|---|---|
| `None` | `None` |
| `""`, `"   "` (пробелы) | `None` |
| `"₽"`, `"руб."`, `"рубль"`, `"рублей"`, `"RUR"` | `"RUB"` |
| `"$"`, `"USD"`, `"доллар"` | `"USD"` |
| `"€"`, `"EUR"`, `"евро"` | `"EUR"` |
| `"₸"`, `"KZT"`, `"тенге"` | `"KZT"` |
| `"₴"`, `"UAH"`, `"гривна"` | `"UAH"` |
| `"£"`, `"GBP"`, `"фунт"` | `"GBP"` |
| Незнакомая строка | `.strip().upper()` как есть |

**Гарантии.** Никогда не бросает. Словарь синонимов расширяемый - пополняйте `_CURRENCY_ALIASES` в `money.py`.

---

## `ParserConfig`

```python
@dataclass(slots=True)
class ParserConfig:
    time_boundary_ratio: float = 0.53
    header_anchor_words: tuple[str, ...] = (...)
    auth_re: re.Pattern[str] = ...
    transfer_bank_re: re.Pattern[str] = ...
    transfer_person_re: re.Pattern[str] = ...
    first_sentence_re: re.Pattern[str] = ...
    footer_phrases: tuple[str, ...] = (...)
    header_marker: str = "код авторизации"
    line_tolerance: int = 3
    header_search_limit: float = 0.8
    shape_window: int = 100
```

**Назначение.** Единая точка настройки парсера. Передаётся в `SberStatementParser(config=...)`. Все поля - публичные.

**Инварианты.** Конструктор бросает `ValueError`, если:

- `time_boundary_ratio` вне `(0, 1)`;
- `header_search_limit` вне `(0, 1]`;
- `line_tolerance <= 0` или `shape_window <= 0`;
- `header_marker` пустой **или состоит только из пробелов**;
- `header_anchor_words` / `footer_phrases` пустые **или содержат
  только пробельные элементы**.

**Чего не делает.** Не валидирует содержимое regex. Если вы переопределяете `transfer_bank_re` и т. п. - за корректность отвечаете сами.

---

## `ColumnLayout`

```python
class Interval(NamedTuple):
    x0: float
    x1: float


@dataclass(slots=True)
class ColumnLayout:
    date:     Interval
    time:     Interval
    category: Interval
    amount:   Interval
    balance:  Interval
```

**Назначение.** Горизонтальные границы пяти колонок таблицы в PDF-координатах (`x0 < x1`, ось X направлена вправо от левого края страницы).

**Вход.** Любые пары `(x0, x1)` (в том числе `int`) или `Interval` - при инициализации нормализуются в `Interval` и приводятся к `float`.

**Инварианты.** Конструктор бросает `ValueError`, если:

- `x0 >= x1` хотя бы в одной колонке;
- колонки идут **не в порядке** `date -> time -> category -> amount -> balance`   или пересекаются между собой.

**Методы:**

| Метод | Что делает |
|---|---|
| `default()` | Рабочий fallback для типовой выписки A4. |
| `to_dict()` | `{"date": {"x0": 45.0, "x1": 102.0}, ...}` - значения всегда `float`. |
| `from_dict(d)` | Обратное преобразование. |

**Чего не делает.** Не проверяет, что координаты попадают в размер страницы - это забота вызывающего кода.

---

## `StatementInfo`

```python
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
```

**Назначение.** Метаданные выписки: кто владелец, какой счёт, за какой период, в какой валюте.

**Постобработка (`__post_init__`):**

- `currency` нормализуется через `normalize_currency`; пустое значение   превращается в `None`.
- Если `period_start > period_end` -> `ValueError`.
- Если `open_date > close_date` -> `ValueError`.

**Метод `to_dict()`** возвращает JSON-совместимый словарь: даты - ISO-строки (`"2026-10-01"`) или `None`.

**Чего не делает.** Не проверяет, что даты вообще есть, - они опциональны.

---

## `Transaction`

```python
@dataclass(slots=True)
class Transaction:
    date: Optional[date] = None
    time: Optional[time] = None
    auth: str = ""
    category: str = ""
    description: str = ""
    counterparty_name: Optional[str] = None
    currency: Optional[str] = None
    amount_raw: str = ""
    balance_raw: str = ""
    amount: Optional[int] = None
    balance: Optional[int] = None
```

**Назначение.** Одна операция по счёту.

**Поля:**

| Поле | Смысл |
|---|---|
| `date` / `time` | Дата и время (секунды всегда 0). |
| `auth` | Код авторизации. `""`, если его нет. |
| `category` | Короткая категория из выписки. |
| `description` | Полное описание операции. |
| `counterparty_name` | Извлечённый контрагент или `None`. |
| `currency` | ISO-код после нормализации или `None`. |
| `amount_raw` / `balance_raw` | Сырые строки как в PDF. |
| `amount` | Сумма в копейках, знак сохраняется. |
| `balance` | Остаток в копейках, всегда `≥ 0`. |

**Постобработка (`__post_init__`):**

- Строковые поля обрезаются по краям (`strip()`).
- `currency` нормализуется через `normalize_currency`; пустое значение   превращается в `None`.
- Пустой `counterparty_name` (`""` или только пробелы) превращается   в `None`.

**Метод `to_dict()`** сериализует `date` в ISO, `time` - в `HH:MM`.

**Чего не делает.** Не проверяет согласованность `amount_raw` и `amount` - если задаёте поля вручную, за консистентность отвечаете сами. Обычно их заполняет парсер из одного источника.

> **Обратите внимание на `currency`:** тип `Optional[str]`. Если
> валюта отсутствует в исходных данных, вернётся `None`, а не `""`.
> Код-потребитель должен учитывать это (`if tx.currency is None: ...`).

---

## `BalanceCheck`

```python
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
```

`BalanceStatus` - `str`-enum с нижним регистром значений:

- `OK` - баланс сошёлся, пропусков нет;
- `MISMATCH` - суммы не сошлись;
- `INCOMPLETE` - суммы сошлись, но часть записей пропущена;
- `INSUFFICIENT_DATA` - меньше двух валидных записей.

**Приоритет статусов** (когда подходит несколько условий):

```
INSUFFICIENT_DATA  >  MISMATCH  >  INCOMPLETE  >  OK
```

**Поля:**

| Поле | Смысл |
|---|---|
| `ok` | `True`, только если `status == OK`. |
| `n_total_records` | Всего транзакций в `ParseResult`. |
| `n_records` | Валидных (у которых есть `amount` и `balance`). |
| `n_skipped` | `n_total_records - n_records`. |
| `oldest_balance` | Остаток до самой старой операции (в копейках). |
| `newest_balance` | Остаток после самой новой операции. |
| `sum_amounts` | Сумма операций **без** самой старой. |
| `expected_newest` | `oldest_balance + sum_amounts`. |
| `diff` | `expected_newest - newest_balance`. `0` = сошлось. |

**`reason` - не источник истины.** Оставлен для логов и человекочитаемого вывода. Ветвиться в коде нужно по `status` и труктурным полям (`diff`, `n_skipped`), а не по тексту.

**Чего не делает.** Не гарантирует, что `ok == True` означает «данные верны» - гарантирует лишь, что **внутренняя арифметика выписки** непротиворечива. Ошибки OCR/парсинга, консистентные арифметически, сверка не поймает.

---

## `ParseResult`

```python
@dataclass(slots=True)
class ParseResult:
    statement: StatementInfo
    transactions: list[Transaction] = field(default_factory=list)
    balance_check: Optional[BalanceCheck] = None
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int: ...
    def to_dict(self) -> dict: ...
```

**Назначение.** Всё, что вернул парсер за один вызов.

**Методы:**

| Метод | Что делает |
|---|---|
| `len(result)` | Возвращает число транзакций. |
| `result.to_dict()` | Полностью JSON-совместимый словарь. |

**Гарантии `to_dict`:**

- Даты - ISO-строки (`"2026-10-01"`).
- Время - `"HH:MM"` (без секунд).
- `BalanceStatus` - `.value` (строка).
- Результат проходит `json.dumps` без `default=`.

**Чего не делает.** Не содержит исходных PDF-координат и не даёт доступ к «сырым» страницам - для отладки используйте `warnings` и логгер.

---

## `SberStatementParser`

```python
class SberStatementParser:
    def __init__(
        self,
        config: Optional[ParserConfig] = None,
        layout: Optional[ColumnLayout] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None: ...

    def parse(self, path: str) -> ParseResult: ...
```

**Назначение.** Точка входа: PDF-файл -> `ParseResult`.

**Параметры конструктора:**

| Параметр | Если не задан |
|---|---|
| `config` | Создаётся `ParserConfig()` по умолчанию. |
| `layout` | Определяется из шапки PDF на каждом вызове. |
| `logger` | Берётся `logging.getLogger(__name__)`. |

**Метод `parse(path)`:**

- Открывает PDF через `pdfplumber` и извлекает метаданные, транзакции и сверяет баланс.
- **Никогда не бросает исключений** на «плохих», но открывающихся PDF: ошибки и предупреждения собираются в `result.warnings`, незаполненные поля остаются `None` / `""`.
- **Пробрасывает исключения `pdfplumber`** на уровне открытия файла (битый файл, нет доступа, не PDF).
- **Бросает** `ValueError`, если в PDF нет страниц.
- **Бросает** `ValueError`, если `StatementInfo.__post_init__` обнаружит некорректные даты (например, `period_start > period_end`). Это касается только «грязных» PDF - при нормальных выписках исключения не будет.

**Побочные эффекты:**

- Пишет `WARNING` и `ERROR` в переданный логгер.
- Каждый вызов `parse` начинает с чистого списка `warnings`.

**Чего не гарантирует:**

- Правильный результат на нестандартном формате выписки. Если шапка не найдена - используется `ColumnLayout.default()` и пишется warning.
- Точность `counterparty_name`: это эвристика (regex + постобработка инициалов). На необычных описаниях может вернуть `None`.
- Скорость на очень больших PDF: страницы разбираются последовательно, без параллелизма.

**Потокобезопасность.** Экземпляр парсера **не потокобезопасен** (внутри копится `self._warnings` на время вызова). Для многопоточности создавайте отдельный экземпляр на поток или вызывайте `parse` под блокировкой.

---

## Памятка: как ветвиться по результату

```python
from sber_parser import SberStatementParser, BalanceStatus

parser = SberStatementParser()
result = parser.parse("statement.pdf")

# 1. Сначала - качество парсинга в целом.
if result.warnings:
    log.warning("PDF разобран с замечаниями: %s", result.warnings)

# 2. Затем - арифметика.
bc = result.balance_check
if bc is None or bc.status != BalanceStatus.OK:
    log.error(
        "сверка баланса: status=%s, diff=%s, skipped=%s/%s",
        bc.status.value, bc.diff, bc.n_skipped, bc.n_total_records,
    )

# 3. Только после этого - бизнес-логика.
for tx in result.transactions:
    if tx.amount is None or tx.balance is None:
        continue                        # запись, которую не удалось разобрать
    ...
```