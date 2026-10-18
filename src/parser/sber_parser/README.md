# Выписки Сбера: парсер PDF

Пакет для извлечения структурированных данных из PDF-выписок Сбербанка: метаданные счёта, список транзакций и автоматическая сверка баланса.

```python
from sber_parser import SberStatementParser

parser = SberStatementParser()
result = parser.parse("statement.pdf")

for tx in result.transactions:
    print(tx.date, tx.amount, tx.counterparty_name)
```

---

## Содержание

1. [Установка](#установка)
2. [Быстрый старт](#быстрый-старт)
3. [Что вы получите на выходе](#что-вы-получите-на-выходе)
4. [Структура пакета](#структура-пакета)
5. [Сверка баланса](#сверка-баланса)
6. [Формат данных и инварианты](#формат-данных-и-инварианты)
7. [Предупреждения и ошибки](#предупреждения-и-ошибки)

---

## Установка

- Python **3.10+**.
- Зависимости: `pdfplumber`.

```bash
pip install pdfplumber
```

Стандартная библиотека покрывает всё остальное: `re`, `decimal`, `datetime`, `dataclasses`.

---

## Быстрый старт

```python
import json
from sber_parser import SberStatementParser

parser = SberStatementParser()
result = parser.parse("statement.pdf")

print(result.statement.fio)              # 'Иванов Иван Иванович'
print(result.statement.currency)         # 'RUB'
print(len(result))                       # число транзакций

if not result.balance_check.ok:
    print("баланс не сошёлся:", result.balance_check.status.value)

with open("out.json", "w", encoding="utf-8") as f:
    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
```

Если формат стабильно известен заранее - можно отдать свой layout и/или конфиг, чтобы не тратить время на автоопределение:

```python
from sber_parser import ParserConfig, ColumnLayout

parser = SberStatementParser(
    config=ParserConfig(line_tolerance=2),
    layout=ColumnLayout(
        date=(45, 102), time=(102, 152),
        category=(152, 370), amount=(370, 462), balance=(462, 560),
    ),
)
```

---

## Что вы получите на выходе

`parse()` возвращает `ParseResult` - один плоский объект со всем содержимым выписки:

```
ParseResult
├── statement        # StatementInfo - метаданные счёта
├── transactions     # list[Transaction]
├── balance_check    # BalanceCheck - результат сверки
└── warnings         # list[str] - что не удалось распознать
```

Пример одной транзакции:

```python
Transaction(
    date=date(2026, 10, 1),
    time=time(12, 34),
    auth="123456",
    category="Переводы",
    description="Перевод от И. Иван Иванов. Операция",
    counterparty_name="И. Иван Иванов",
    currency="RUB",
    amount_raw="-1 500,00",
    balance_raw="12 345,67",
    amount=-150000,          # копейки, списание
    balance=1234567,         # копейки, остаток
)
```

`result.to_dict()` - полностью JSON-совместимое представление (даты - ISO-строки, время - `HH:MM`).

---

## Структура пакета

```
sber_parser/
├── money.py       # парсинг дат / времени / сумм + нормализация валюты
├── config.py      # ParserConfig, ColumnLayout
├── models.py      # StatementInfo, Transaction, BalanceCheck, ParseResult
└── sber_pdf.py      # SberStatementParser — точка входа
```

**Поток данных:**

```
PDF --> SberStatementParser.parse() --> ParseResult
                │
                ├── StatementInfo
                ├── [Transaction]
                ├── BalanceCheck
                └── [warnings]
```

---

## Сверка баланса

В выписке Сбера у каждой операции указан остаток **после** неё. Это позволяет проверить арифметику, не доверяя формату на слово:

```
oldest_balance + sum(amount(все операции, кроме самой старой))
        == newest_balance
```

Если равенство не выполняется

| `status` | Что значит |
|---|---|
| `OK` | Всё сошлось, все записи распознаны. |
| `MISMATCH` | Суммы не сошлись. Смотрите `diff`. |
| `INCOMPLETE` | Суммы сошлись, но часть записей пропущена. |
| `INSUFFICIENT_DATA` | Меньше двух валидных записей. |

`balance_check.diff` - расхождение в копейках. `n_skipped` - сколько
транзакций не удалось разобрать.

---

## Формат данных и инварианты

- **Деньги - целые копейки.** Округление при разборе - `ROUND_HALF_UP` до копеек.
- **Знак суммы.** `amount > 0` - пополнение, `amount < 0` - списание. В Сбере «сырая» строка без знака означает списание.
- **Баланс - всегда `≥ 0`.** Это остаток после операции.
- **Даты и время** - `datetime.date` и `datetime.time` (секунды всегда `0`, часовые пояса не участвуют).
- **Валюта** - ISO 4217 (`RUB`, `USD`, `EUR`). Незнакомые строки остаются в верхнем регистре как есть.
- **Порядок транзакций** - как в PDF: сверху вниз, от новых к старым.

---

## Предупреждения и ошибки

- **Исключения бросаются только на неправильных аргументах конструкторов** (`ParserConfig`, `ColumnLayout`, `StatementInfo`). Это защита от опечаток в коде, а не от «грязных» PDF.
- **Всё, что связано с качеством исходных данных**, отражается через`result.warnings` и `balance_check.status`.
- Парсер **не бросает исключений на «неидеальном» PDF**: если шапка таблицы не найдена, будет использован layout по умолчанию, а в `warnings` появится соответствующая строка.
