# `src.importing` - подготовка данных и импорт в БД

Пакет отвечает за: (a) чистую подготовку `ParseResult` -> `PreparedStatement`, (b) вставку в БД с дедупликацией, (c) автосоздание категорий при импорте.

`prepare.py` **не обращается к БД** и не пишет файлов (только читает PDF для `compute_file_hash_from_path`). `import_to_db.py` и `categories.py` принимают `Session` снаружи (unit-of-work), **не коммитят** - только `flush()`.

## Публичный API (`src.importing/__init__.py`)

```python
# Хэши
compute_file_hash(data: bytes) -> str
compute_file_hash_from_path(path: str, chunk_size: int = 8192) -> str
compute_transaction_hash(
    *, account_key, date=None, time=None, amount=None, currency=None,
    description=None, counterparty_name=None, auth=None, version=None,
) -> tuple[str, int]

# Подготовка (чистая, без БД)
prepare_transaction(
    *, account_id, account_currency, account_key=None,
    date=None, time=None, amount=None, currency=None,
    description=None, counterparty_name=None, auth=None,
    category=None, original_index=-1,
) -> PreparedTransaction
prepare_statement(
    result, account_id, account_currency, file_path, *, account_key=None,
) -> PreparedStatement

# DTO
PreparedTransaction, PreparedStatement, IntraBatchCollision
IntraBatchCollision(transaction_hash, transactions)

# Коды валидации
ERR_MISSING_DATE, ERR_MISSING_AMOUNT,
ERR_CURRENCY_NONE_MULTI, ERR_CURRENCY_MISMATCH

# Импорт в БД
import_prepared_statement(session, prepared, *, chunk_size=500) -> ImportResult
import_with_categories(session, prepared, *, auto_create_categories=True, chunk_size=500) -> ImportResult
ImportResult(status, statement_id, inserted_transactions,
             skipped_intra_batch, skipped_cross_batch,
             created_categories, warnings)
IntraBatchSkip, CrossBatchSkip
```

> **Duck typing.** Все публичные функции принимают поля транзакции, а не объект парсера. Это позволяет переиспользовать их для ручного ввода (`add_manual_transaction` в `src.transactions` так и делает).

> **`account_key`.** Стабильный идентификатор счёта в хэше. Default - `str(account_id)` (см. `make_account_key`). Для стабильности при пересоздании БД передавайте `Account.business_key()` (`"bank:{bank_name}:{account_number_masked}"`).

## Инварианты `PreparedStatement`

- `transactions_to_insert` - все `is_valid=True`, включая участников `intra_batch_collisions` (B1 только помечает, решает B2).
- `rejected` - только `is_valid=False`, порядок сохранён.
- `intra_batch_collisions` - группы валидных с одинаковым `transaction_hash` (≥ 2 элементов). Порядок - по первому появлению.
- `warnings` - `result.warnings` + наши. Порядок: сначала парсер.
- `file_hash` - SHA-256 содержимого файла (чанки 8 КБ).
- `file_name` - `os.path.basename(file_path)`.
- `_raw_statement_info` - `StatementInfo` из `result.statement` as-is (для B2d / UI). **НЕ для записи в БД.**
- `period_start` / `period_end` - из `result.statement`.
- `balance_check` - пробрасывается.

## `PreparedTransaction` - поля и нормализация

| Поле | Тип | Нормализация |
| :--- | :--- | :--- |
| `account_id` | `int` | обязателен |
| `date` | `Optional[date]` | `_to_date` |
| `time` | `Optional[time]` | `_to_time` - секунды/микросекунды обнуляются |
| `amount` | `Optional[int]` | копейки, `int` |
| `currency` | `Optional[str]` | `.upper()`, дефолт из `account_currency` |
| `description` | `Optional[str]` | `_norm` (strip, NBSP->space); `""` -> `None` |
| `counterparty_name` | `Optional[str]` | `_norm`; `""` -> `None` |
| `authorization_code` | `Optional[str]` | strip; `""` -> `None` |
| `raw_category` | `Optional[str]` | strip; `""` -> `None` |
| `is_transfer` | `bool` | всегда `False` в B1 |
| `source` | `str` | `"pdf"` |
| `transaction_hash` | `str` | sha256 hex |
| `hash_version` | `int` | `CURRENT_HASH_VERSION` |
| `original_index` | `int` | индекс в `result.transactions` |
| `is_valid` / `validation_errors` | `bool` / `tuple[str, ...]` | см. коды ниже |

> Нормализация `_norm` применяется один раз - к `description` и `counterparty_name` - и используется и для хэша, и для `PreparedTransaction`. Это гарантирует, что `prepare_transaction` даёт одинаковый `description` в БД и в хэше. `update_transaction` в `src.transactions` нормализует `description` тем же правилом (`""`/`" "` -> `None`).

## Коды `validation_errors`

| Код | Причина |
| :--- | :--- |
| `missing_date` | `date is None` |
| `missing_amount` | `amount is None` |
| `currency_none_multi` | `currency is None` и `account_currency == "MULTI"` |
| `currency_mismatch` | `currency` задан, `account_currency != "MULTI"` и они различаются |

> **Не реализовано (defense-in-depth):** `ERR_CURRENCY_UNSUPPORTED` - если `currency` не в `TRANSACTION_CURRENCIES`. Сейчас при `currency="GBP"` на `MULTI`-счёте `prepare_transaction` пройдёт валидацию, а `session.flush()` бросит `IntegrityError` (`CHECK ck_transactions_currency`). Планируется добавить на уровне `prepare_transaction`, чтобы и PDF-путь, и `add_manual_transaction` получали `ValueError` до `flush()`.

## Правила `prepare_transaction`

- `account_id is None` -> `ValueError`.
- `auth: ""` (после strip) -> `authorization_code = None`.
- `currency is None` + `account_currency != "MULTI"` -> подставить `account_currency`.
- `currency is None` + `account_currency == "MULTI"` -> reject `currency_none_multi`.
- `currency != account_currency` + `account_currency != "MULTI"` -> reject `currency_mismatch` (агрегированный warning в `prepare_statement`).
- `date is None` -> reject `missing_date`.
- `amount is None` -> reject `missing_amount`.
- `raw_category = (category or "").strip() or None`.
- `is_transfer = False` (B1; пользователь/автоматика - вне B1).
- `source = "pdf"`, `hash_version = CURRENT_HASH_VERSION`.
- `transaction_hash` считается всегда, в т.ч. для `rejected`.

## Дополнительные `warnings` (в `prepare_statement`)

- **L1** (statement vs account): `result.statement.currency` задан, `account_currency != "MULTI"` и они различаются -> одно предупреждение.
- **L2** (агрегат): среди `rejected` есть `currency_mismatch` -> одно предупреждение с числом отклонённых.
- **no-auth**: среди `transactions_to_insert` есть `authorization_code is None` -> одно предупреждение с числом. При наличии `intra_batch_collisions` - усиленный вариант («различить по хэшу невозможно»).

## Правило хэша v1

`transaction_hash` - детерминированный SHA-256 от канонической строки.
Пара `(account_id, transaction_hash)` имеет `UniqueConstraint` в БД.

### Формула

```python
account_key = account_key or make_account_key(account_id)  # str(account_id)

def norm(s):
    return (s or "").strip().replace("\u00a0", " ")

s_acct = account_key
s_date = date.isoformat() if date else ""
s_time = time.strftime("%H:%M") if time else ""
s_amt  = str(amount) if amount is not None else ""
s_cur  = (currency or "").upper()
s_desc = norm(description)
s_cp   = norm(counterparty_name)
s_auth = norm(auth)

payload = "|".join([
    f"v{version}",
    f"acct:{len(s_acct)}:{s_acct}",
    f"date:{len(s_date)}:{s_date}",
    f"time:{len(s_time)}:{s_time}",
    f"amt:{len(s_amt)}:{s_amt}",
    f"cur:{len(s_cur)}:{s_cur}",
    f"desc:{len(s_desc)}:{s_desc}",
    f"cp:{len(s_cp)}:{s_cp}",
    f"auth:{len(s_auth)}:{s_auth}",
])
transaction_hash = sha256(payload.encode("utf-8")).hexdigest()
```

### Что входит в хэш

`version`, `account_key`, `date`, `time`, `amount`, `currency`, `description`, `counterparty_name`, `auth`.

### Что НЕ входит

`category`, `raw_category`, `is_transfer`, `statement_id`, `balance`, `balance_raw`, `amount_raw`.

### Нормализация полей

| Поле | Правило |
| :--- | :--- |
| `account_key` | `str`, непустой; дефолт `str(account_id)`; пустой -> `ValueError` |
| `date` | `date.isoformat()` или `""`; `datetime` -> `.date()` |
| `time` | `strftime("%H:%M")` или `""`; секунды игнорируются |
| `amount` | `str(int)` или `""` |
| `currency` | `.upper()` или `""` |
| `description` | `_norm` или `""` |
| `counterparty_name` | `_norm` или `""` (`None` ≡ `""`) |
| `auth` | `_norm` или `""` (`None` ≡ `""`) |

Не применяем: `casefold`/`lower`, `unicodedata.normalize`, схлопывание внутренних пробелов.

### `account_key` - стабильность при пересоздании БД

`account_key = str(account_id)` привязан к PK. После `drop tables` / пересоздания БД `account_id` меняется -> хэши меняются ->
повторный импорт тех же PDF создаст дубликаты (не поймает `duplicate_statement` по `file_hash`, но `skipped_cross_batch` по хэшу уже не сработает).

**Правило:** в UI передавайте `account_key=account.business_key()` (`"bank:{bank_name}:{account_number_masked}"`). Тогда хэши стабильны независимо от PK и переживают пересоздание БД.

### Известные ограничения v1 (осознанные)

- **Case-sensitive** - `"PYATEROCHKA"` ≠ `"Pyaterochka"` -> разные хэши. Причина: `casefold` повышает риск ложной склейки (две разные сущности -> одинаковый хэш -> потеря денег).
- **Без Unicode-нормализации** - `"Café"` в NFC и NFD дадут разные хэши.
- **Без схлопывания внутренних пробелов** - `"Coffee Shop"` ≠ `"Coffee  Shop"`.
- **`is_transfer` не участвует** - `True` даёт тот же хэш, что `False`.
- **Хэш для `rejected` считается всегда** - «нестабилен по смыслу», не использовать для дедупликации.

### Эталон

```text
account_id=1, date=2024-01-15, time=12:34, amount=-15000, currency="RUB",
description="Оплата в магазине", counterparty_name="PYATEROCHKA", auth="AUTH123"
```

```text
v1|acct:1:1|date:10:2024-01-15|time:5:12:34|amt:6:-15000|cur:3:RUB|desc:17:Оплата в магазине|cp:11:PYATEROCHKA|auth:7:AUTH123
```

| Сценарий | Результат |
| :--- | :--- |
| E2 идемпотентность | `= E1` |
| E3 `auth="AUTH999"` | `<> E1` |
| E4a `auth=None` vs E4b `auth=""` | `= между собой, <> E1 (auth:0:)` |
| E5a `cp=None` vs E5b `cp=""` | `= между собой, <> E1 (cp:0:)` |
| E6 `description=" Оплата в магазине "` | `= E1 (strip)` |
| E7 `account_id=2` | `<> E1` |
| E8 `version=2` | `<> E1` |
| E9 другой `amount_raw` | `= E1 (в payload не входит)` |
| E10 две одинаковые без auth | `= между собой (ожидаемая коллизия)` |
| E11 `12:34:15` vs `12:34:45` | `= между собой (секунды игнорируются)` |
| E12a `desc="a\|b"`, `cp="c"` vs E12b `desc="a"`, `cp="b\|c"` | `<>` (длина-префикс) |

## B2a - импорт в БД (`import_to_db.py`)

`import_prepared_statement(session, prepared, *, chunk_size=500) -> ImportResult`

- Не создаёт сессию (unit-of-work, принимает снаружи).
- **Не коммитит:** `flush()` для получения PK; `commit` / `rollback` - за вызывающим.
- Счёт нельзя переопределить здесь - хэши привязаны к `account_id`. Если нужен другой счёт - пересчитайте в B1 (`prepare_statement` заново).
- `chunk_size` - для `IN (...)` (исторический лимит 999; в новых - 32766). 500 - безопасный дефолт.

### Статусы `ImportResult`

| `status` | Когда | `statement_id` |
| :--- | :--- | :--- |
| `duplicate_statement` | `file_hash` уже есть в БД | существующий `statement_id` |
| `no_valid_transactions` | `transactions_to_insert` пуст | `None`, `Statement` не создаётся |
| `ok` | вставлено > 0 или все валидные попали в skip | `statement_id` нового `Statement` |

> **Про «ok с пустым `inserted_transactions`»:** все валидные транзакции ушли в `skipped_intra_batch` / `skipped_cross_batch`. `Statement` всё равно создан (фиксируем `file_hash`, чтобы повторная загрузка ловилась как `duplicate_statement`). `warnings` содержит предупреждение.

### Правила

- `file_hash` фиксируется всегда при `status="ok"`, даже если ни одна транзакция не вставлена - защита от повторного импорта.
- Intra-batch: оставляем `group.transactions[0]` (минимальный `original_index`); остальные - `IntraBatchSkip`.
- Cross-batch: пропускаем транзакции, чей `transaction_hash` уже есть в БД для этого `account_id`; в `CrossBatchSkip` сохраняем `existing_transaction_id`.
- Ручные правки не перетираются: импорт не обновляет существующие транзакции.
- Несколько импортов в одной сессии - допустимы; `commit` один.

## B2b - категории (`categories.py`)

`import_with_categories(session, prepared, *, auto_create_categories=True, chunk_size=500) -> ImportResult`

- Обёртка над `import_prepared_statement` (B2a).
- Dedup по `file_hash` - **до** создания категорий.
- `to_insert` пуст -> категории не создаются.
- `auto_create_categories=False` -> делегирует B2a без изменений.
- Всё в одной транзакции (`commit`/`rollback` - за вызывающим).

### `infer_category_type(amount, is_transfer)`

| Условие | Тип |
| :--- | :--- |
| `is_transfer=True` | `transfer` (приоритет) |
| `amount > 0` | `income` |
| `amount <= 0` / `amount is None` | `expense` |

### `find_or_create_category(session, name, type, parent_id=None)`

- Поиск по `(name, parent_id)` - exact match, case-sensitive.
- `name=""` / только пробелы -> `ValueError`.
- Существующая категория с другим `type` -> переиспользуется + warning.
- Одна `raw_category` с разными inferred types в одном батче -> warning, категория получает сортировочно-первый тип (`expense < income < transfer`).
- `raw_category=None` / `""` / `" "` -> категория не создаётся, `category_id` остаётся `None`.

### `ImportResult.created_categories`

`tuple[int, ...]` - id новых категорий (переиспользованные не входят).
UI может сходить за именами:

```sql
SELECT category_id, name FROM categories WHERE category_id IN (...)
```

> **Известное ограничение (race):** если между pre-check `_find_existing_statement_id` и вызовом `import_prepared_statement` `statement` с тем же `file_hash` появится (второй процесс / параллельный rerun), `import_with_categories` вернёт `duplicate_statement`, но `created_categories` уже создаст (осиротевшие категории). Для single-writer v1 неактуально; при появлении конкуренции - оборачивать в `SAVEPOINT` или проверять статус перед возвратом.

## CRUD категорий

CRUD (`create_category`, `rename_category`, `delete_category`) живёт в `src.categories` - здесь только импорт-специфичная логика. См. `src/categories/README.md`.
```