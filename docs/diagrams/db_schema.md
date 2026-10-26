# Схема базы данных

- **Версия схемы:** `CURRENT_SCHEMA_VERSION = 2` (`src/db/migrations.py`).
- **СУБД:** SQLite (файл `data/db/finance.db`).
- **ORM:** SQLAlchemy 2.x (`Mapped` / `mapped_column`).
- **Миграции:** лёгкий механизм через `schema_version` (`src/db/migrations.py`).

## Общие принципы

- Денежные суммы хранятся в целых копейках (`INTEGER`), чтобы избежать ошибок округления с плавающей точкой. Поле `amount` знаковое: `+` - доход, `−` - расход.
- Даты - `DATE` в ISO-8601 (`YYYY-MM-DD`).
- Время - `TIME` (`HH:MM:SS`); в v1 секунды всегда `0` (парсер отбрасывает).
- Временные метки - `DATETIME` в UTC (`CURRENT_TIMESTAMP`).
- Идентификаторы - `INTEGER PRIMARY KEY AUTOINCREMENT`.
- Перечисления - через `CHECK`-ограничения (строки из `src/db/constants.py`).
- `PRAGMA foreign_keys = ON` устанавливается на каждом соединении через `@event.listens_for(Engine, "connect")` в `src/db/engine.py`. Без этого `ON DELETE CASCADE` / `ON DELETE SET NULL` в SQLite не работают.
- `WAL` + `busy_timeout=5000` - для снижения `database is locked` при конкурентном доступе.
- Дедупликация:
  - выписки - `UNIQUE(statements.file_hash)`;
  - транзакции - `UNIQUE(transactions.account_id, transactions.transaction_hash)`.

## `schema_version`

Служебная таблица механизма миграций. Создаётся автоматически при `init_db()`.

| Поле | Тип | Ограничения | Описание |
| :--- | :--- | :--- | :--- |
| `version` | `INTEGER` | `PK` | Применённая версия схемы |
| `applied_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Когда применена |

`CURRENT_SCHEMA_VERSION = 2` (см. `src/db/migrations.py`). В таблице - все применённые версии (накапливаются: `1, 2, …`). `MAX(version)` = текущая версия БД.

## `accounts`

Банковский счёт. В v1 поддерживается несколько счетов: первый создаётся либо из PDF-выписки Сбера (автоматически, через `find_or_create_account`), либо вручную во вкладке «Счета» (`src/ui/pages/accounts.py`).

| Поле | Тип | Ограничения | Описание |
| :--- | :--- | :--- | :--- |
| `account_id` | `INTEGER` | `PK`, `AUTOINCREMENT` | Идентификатор счёта |
| `bank_name` | `TEXT` | `NOT NULL` | Название банка |
| `account_name` | `TEXT` | `NOT NULL` | Отображаемое имя счёта («Основной», «Зарплатный») |
| `account_number_masked` | `TEXT` | `NOT NULL` | Маскированный номер счёта (`"**** 1234"`) |
| `currency` | `TEXT` | `NOT NULL`, `CHECK (currency IN ('RUB','USD','EUR','MULTI'))` | Валюта счёта; `MULTI` - мультивалютный |
| `fio` | `TEXT` | `NULL` | ФИО владельца |
| `card_number_masked` | `TEXT` | `NULL` | Маскированный номер карты |
| `open_date` | `DATE` | `NULL` | Дата открытия счёта |
| `close_date` | `DATE` | `NULL` | Дата закрытия счёта (`NULL` - активен) |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Дата создания записи |
| `updated_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `ON UPDATE CURRENT_TIMESTAMP` | Дата последнего обновления |

**Ограничения:**

- `UNIQUE(bank_name, account_number_masked)` - `uq_accounts_bank_number`. Бизнес-ключ для `find_or_create_account`.
- `CHECK(open_date IS NULL OR close_date IS NULL OR open_date <= close_date)` - `ck_accounts_dates_order`.
- `CHECK(currency IN ('RUB','USD','EUR','MULTI'))` - `ck_accounts_currency`.

**Индексы:**

- `PK account_id`;
- `UNIQUE(bank_name, account_number_masked)`.

**Бизнес-ключ для хэширования:** метод `Account.business_key() -> "bank:{bank_name}:{account_number_masked}"`. Используется в UI-2/UI-5 при передаче `account_key` в `prepare_statement` / `add_manual_transaction`. Не меняется при пересоздании БД (в отличие от `str(account_id)`). Ограничение: при `update_account(bank_name=...)` или `account_number_masked=...` ключ меняется -> новые транзакции по этому счёту получат другой `transaction_hash`.

**Каскады:**

- `Account.statements` - `passive_deletes=True` (ORM не загружает коллекцию; при `delete_account(cascade=True)` CRUD сам делает bulk `DELETE`, затем БД добивает FK `CASCADE`).
- `Account.transactions` - аналогично.

## `statements`

Загруженная выписка (PDF). Одна выписка привязана к одному счёту.

| Поле | Тип | Ограничения | Описание |
| :--- | :--- | :--- | :--- |
| `statement_id` | `INTEGER` | `PK`, `AUTOINCREMENT` | Идентификатор выписки |
| `account_id` | `INTEGER` | `NOT NULL`, `FK -> accounts.account_id`, `ON DELETE CASCADE` | Счёт-владелец выписки |
| `file_name` | `TEXT` | `NOT NULL` | Имя загруженного файла (`basename`) |
| `period_start` | `DATE` | `NULL` | Начало периода выписки |
| `period_end` | `DATE` | `NULL` | Конец периода выписки |
| `file_hash` | `TEXT` | `NOT NULL`, `UNIQUE` | SHA-256 содержимого PDF |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | |
| `updated_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `ON UPDATE CURRENT_TIMESTAMP` | |

**Ограничения:**

- `UNIQUE(file_hash)` - дедупликация выписок.
- `CHECK(period_start IS NULL OR period_end IS NULL OR period_start <= period_end)` - `ck_statements_period_order`.

**Индексы:**

- `PK statement_id`;
- `UNIQUE(file_hash)`;
- `INDEX(account_id)` - `ix_statements_account_id`.

**Назначение `file_hash`.** SHA-256 от содержимого PDF. Позволяет распознать повторную загрузку той же выписки. При совпадении UI-2 (`src/ui/pages/upload.py::_render_duplicate_block`) показывает warning и предлагает две опции:

1. «Удалить старую выписку и импортировать заново» - двухшаговое подтверждение, вызывает `delete_statement(cascade_transactions=True)` (удаляются и выписка, и все её транзакции), после чего импорт можно повторить.
2. «Отмена» - состояние сбрасывается, файл можно перезагрузить.

«Дополнение» и «перезапись без удаления» в UI не реализованы.

**Relationship `Statement.transactions`:** `cascade="save-update, merge"`, `passive_deletes="all"`. Ключевое решение: при `session.delete(stmt)` ORM никогда не эмитит `DELETE` для транзакций - БД обнуляет `statement_id` через `ON DELETE SET NULL`. Это позволяет `delete_statement(cascade_transactions=False)` не терять данные даже при загруженной коллекции.

## `transactions`

Транзакция из выписки или добавленная вручную.

| Поле | Тип | Ограничения | Описание |
| :--- | :--- | :--- | :--- |
| `transaction_id` | `INTEGER` | `PK`, `AUTOINCREMENT` | Идентификатор транзакции |
| `account_id` | `INTEGER` | `NOT NULL`, `FK -> accounts.account_id`, `ON DELETE CASCADE` | Счёт транзакции |
| `statement_id` | `INTEGER` | `NULL`, `FK -> statements.statement_id`, `ON DELETE SET NULL` | Выписка-источник; `NULL` для ручных и API-транзакций, а также для транзакций удалённой выписки |
| `date` | `DATE` | `NOT NULL` | Дата транзакции |
| `time` | `TIME` | `NULL` | Время транзакции (может отсутствовать) |
| `amount` | `INTEGER` | `NOT NULL` | Сумма в копейках, знаковая |
| `currency` | `TEXT` | `NOT NULL`, `CHECK (currency IN ('RUB','USD','EUR'))` | Фактическая валюта транзакции. Для MULTI-счёта может отличаться от `accounts.currency` |
| `description` | `TEXT` | `NULL` | Описание из выписки (нормализуется: `""` -> `NULL`) |
| `counterparty_name` | `TEXT` | `NULL` | Контрагент |
| `category_id` | `INTEGER` | `NULL`, `FK -> categories.category_id`, `ON DELETE SET NULL` | Категория транзакции |
| `authorization_code` | `TEXT` | `NULL` | Код авторизации из выписки; может отсутствовать |
| `raw_category` | `TEXT` | `NULL` | «Сырая» категория из выписки (парсер: `Transaction.category`) |
| `is_transfer` | `INTEGER` | `NOT NULL`, `DEFAULT 0`, `CHECK (is_transfer IN (0, 1))` | `1` - перевод между своими счетами (исключается из статистики); `0` - обычная |
| `transaction_hash` | `TEXT` | `NOT NULL` | Хэш транзакции для дедупликации; уникален в рамках счёта |
| `hash_version` | `INTEGER` | `NOT NULL`, `DEFAULT 1`, `CHECK (hash_version >= 1)` | Версия формулы `transaction_hash` (`MIN_HASH_VERSION = 1`) |
| `source` | `TEXT` | `NOT NULL`, `CHECK (source IN ('pdf','csv','api','manual'))` | Источник. В v1 фактически используются `pdf` (импорт выписки) и `manual` (ручное добавление); `csv` и `api` зарезервированы |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | |
| `updated_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `ON UPDATE CURRENT_TIMESTAMP` | |

**Ограничения:**

- `UNIQUE(account_id, transaction_hash)` - `uq_transactions_account_hash`.
- `CHECK(currency IN ('RUB','USD','EUR'))` - `ck_transactions_currency`.
- `CHECK(source IN ('pdf','csv','api','manual'))` - `ck_transactions_source`.
- `CHECK(is_transfer IN (0, 1))` - `ck_transactions_is_transfer`.
- `CHECK(hash_version >= 1)` - `ck_transactions_hash_version`.

**Индексы:**

- `PK transaction_id`;
- `UNIQUE(account_id, transaction_hash)`;
- `INDEX(date)` - `ix_transactions_date`;
- `INDEX(account_id, date)` - `ix_transactions_account_date`;
- `INDEX(statement_id)` - `ix_transactions_statement_id`;
- `INDEX(category_id)` - `ix_transactions_category_id`.

**Удалённые индексы (по сравнению с v1):**

- `ix_transactions_is_transfer` - удалён в миграции v2. Обоснование: `is_transfer` принимает два значения; планировщик SQLite почти всегда игнорирует такой индекс. При реальной необходимости - вернуть как композитный `(account_id, is_transfer)` после замеров.
- `ix_transactions_raw_category` - не создавался (в v1 full scan на `WHERE raw_category = ?` допустим при малых объёмах). При росте `>10k` строк - добавить partial index:

```sql
CREATE INDEX ix_transactions_raw_category
    ON transactions (raw_category)
    WHERE raw_category IS NOT NULL;
```

### Назначение `transaction_hash` (формула v1, `hash_version = 1`)

Хэш вычисляется `src/importing/prepare.py::compute_transaction_hash` от единого набора полей:

```text
(account_key, date, time, amount, currency,
 description, counterparty_name, auth, version)
```

**Правила:**

- `account_key` - **не** `account_id`. Передаётся вызывающим кодом:
  - UI-2 (`upload.py`) и UI-5 (`add_transaction.py`) передают `Account.business_key()` -> `"bank:{bank_name}:{account_number_masked}"`.
  - Если `account_key` не передан - fallback `str(account_id)`.
- `date`, `time` - нормализуются (`datetime` -> `date`, `datetime` -> `time` без секунд; невалидная строка -> `None`).
- `auth`, `description`, `counterparty_name` - нормализация `_norm`: `None`, `""`, `" "` эквивалентны. Trailing/leading whitespace и NBSP -> обычный пробел.
- `amount` - копейки (знаковое).
- `currency` - ISO-код (`RUB`/`USD`/`EUR`).
- `version` - `hash_version` (сейчас всегда `1`).

Нет ветвления по `authorization_code`. `auth` участвует в хэше всегда, как одно из полей; отдельной «короткой» формулы без `time`/`amount`/`currency`/`description` не существует.

**Дедупликация** - строго по `UNIQUE(account_id, transaction_hash)`. Никакого дополнительного «сравнения сопоставимых полей» при совпадении хэша нет. `add_manual_transaction` бросает `DuplicateTransactionError` при первом совпадении (см. `src/transactions/crud.py`, тест `test_duplicate_raises`).

**Известное ограничение.** При `update_transaction(description=...)` или `update_transaction(counterparty_name=...)` хэш не пересчитывается - он остаётся снимком на момент импорта. Это осознанно: дедупликация ищет «ту же транзакцию», а не «транзакцию с тем же описанием». См. docstring `update_transaction`.

**Известное ограничение (ё/е).** Поиск по `description`/`counterparty_name` (`description_query`) не находит «Пятерочка» по запросу «Пятёрочка» - `ё` и `е` разные символы, `lower()` их не сближает. Решение - отдельная задача (кастомный `lower_ru` или preprocessing).

## `categories`

Справочник категорий. Поддерживает иерархию через `parent_category_id`.

| Поле | Тип | Ограничения | Описание |
| :--- | :--- | :--- | :--- |
| `category_id` | `INTEGER` | `PK`, `AUTOINCREMENT` | Идентификатор категории |
| `name` | `TEXT` | `NOT NULL` | Название |
| `type` | `TEXT` | `NOT NULL`, `CHECK (type IN ('income','expense','transfer'))` | Тип категории |
| `parent_category_id` | `INTEGER` | `NULL`, `FK -> categories.category_id`, `ON DELETE SET NULL` | Родительская категория; `NULL` - корневая |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | |
| `updated_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `ON UPDATE CURRENT_TIMESTAMP` | |

**Ограничения:**

- `UNIQUE(name, parent_category_id)` - `uq_categories_name_parent` (для дочерних категорий).
- `CHECK(type IN ('income','expense','transfer'))` - `ck_categories_type`.

**Индексы:**

- `PK category_id`;
- `UNIQUE(name, parent_category_id)`;
- partial `UNIQUE uq_categories_name_root` - `UNIQUE(name) WHERE parent_category_id IS NULL`. Нужен потому, что в SQL `NULL != NULL`, и обычный `UNIQUE(name, parent_category_id)` не ловит дубли корней.
- `INDEX(parent_category_id)` - `ix_categories_parent_category_id`.

**Примечание про `type='transfer'`.** Категории типа «перевод» относятся к переводам самому себе. Признак `is_transfer` в `transactions` устанавливается вручную пользователем (UI-3 «Отметка переводов») и не выводится автоматически из `category.type`.

## Связи (FK)

| От | К | Тип | `ON DELETE` |
| :--- | :--- | :--- | :--- |
| `accounts` | `statements` | 1 : M | `CASCADE` |
| `accounts` | `transactions` | 1 : M | `CASCADE` |
| `statements` | `transactions` | 1 : M | `SET NULL` |
| `categories` | `transactions` | 1 : M | `SET NULL` |
| `categories` | `categories` (parent) | 1 : M | `SET NULL` |

**Ключевое изменение v2:** `statements -> transactions` - `ON DELETE SET NULL` (было `CASCADE`). Удаление выписки не удаляет транзакции, а отвязывает их (`statement_id = NULL`). Удаление транзакций - ответственность CRUD (`delete_statement(cascade_transactions=True/False)`).

**ORM-уровень:**

- `Statement.transactions` - `passive_deletes="all"`: ORM никогда не эмитит `DELETE` для детей, БД обнуляет FK.
- `Account.statements`, `Account.transactions` - `passive_deletes=True`: при `delete_account(cascade=True)` CRUD сам делает bulk `DELETE`, затем `session.delete(account)`.
- `Category.children`, `Category.transactions` - `passive_deletes=True`: БД обнуляет FK.

## Дедупликация

**Выписки.** `UNIQUE(statements.file_hash)`. При совпадении UI-2:

- показывает warning с информацией о существующей выписке (`file_name`, период, когда загружена);
- предлагает удалить старую выписку и импортировать заново (двухшаговое подтверждение, `delete_statement(cascade_transactions=True)`);
- либо отменить загрузку.

**Транзакции.** `UNIQUE(account_id, transaction_hash)`. Хэш вычисляется в `src/importing/prepare.py` (формула - см. выше). `hash_version` позволяет менять формулу в будущем без пересчёта существующих записей.

При импорте выписки:

- `skipped_intra_batch` - транзакции с одинаковым `transaction_hash` внутри одной выписки (сохраняется та, у которой меньше `original_index`; остальные попадают в отчёт).
- `skipped_cross_batch` - транзакции, чей `transaction_hash` уже есть в БД (по этому `account_id`).

## Переводы

- `transactions.is_transfer = 1` устанавливается вручную (UI-3, вкладка «Статистика» -> «Отметка переводов» -> `data_editor` с чекбоксом).
- Переводы исключаются из расчёта `income` / `expense` / `net` / `count` (`src/stats/summary.py::get_summary`).
- В `Summary` есть отдельное поле `transfer_count` - число переводов за период.
- Переводы третьим лицам (`is_transfer = 0`) учитываются как обычные транзакции.

## Категории

- Пользователь может создавать, переименовывать и удалять категории (UI-4, вкладка «Категории» -> «Справочник»).
- Уникальность: `UNIQUE(name, parent_category_id)` для дочерних; partial `UNIQUE WHERE parent_category_id IS NULL` для корневых.
- При удалении категории:
  - у связанных транзакций `category_id` -> `NULL` (FK `SET NULL`);
  - у дочерних категорий `parent_category_id` -> `NULL` (FK `SET NULL` - они становятся корневыми).
- Bulk-назначение: `assign_category_to_raw_group` проставляет `category_id` всем транзакциям с заданным `raw_category` и `category_id IS NULL` (уже назначенные не перезаписываются). Валидация `category_id` (`_validate_category_id`) - до `UPDATE`.

## Согласование валют

- Если `accounts.currency = 'MULTI'` - `transactions.currency` может быть любым из (`'RUB'`,`'USD'`,`'EUR'`).
- Если `accounts.currency` - конкретная валюта, `transactions.currency` должен совпадать с ней.
- Проверка выполняется на уровне приложения (`prepare_transaction`), в БД - только `CHECK` на допустимые значения.
- Для MULTI-счёта `currency=None` при ручном добавлении -> `ERR_CURRENCY_NONE_MULTI`; `currency="GBP"` -> `ERR_CURRENCY_UNSUPPORTED`.

**Известное ограничение:** `Summary.income` / `expense` для MULTI-счёта складывают копейки разных валют как `int` - число бессмысленно. В v1 пользователь сам следит за этим; в будущем - параметр `currency` в `get_summary` или разбивка по валютам в UI-3.

## Миграции

| Версия | Что | Файл |
| :--- | :--- | :--- |
| 1 | Начальная схема v1 | (без миграции, создаётся `create_all`) |
| 2 | `transactions.statement_id`: `ON DELETE CASCADE` -> `ON DELETE SET NULL`. Удалён `ix_transactions_is_transfer`. | `src/db/migrations.py::_migrate_to_v2` |

**Механизм (`src/db/migrations.py`):**

- `schema_version.version` - `PK`; `MAX(version)` = текущая версия БД.
- `run_migrations(engine)` - применяет по одной в отдельной транзакции (`engine.begin()`), после каждой вызывает `PRAGMA foreign_key_check`.
- `init_fresh_schema(engine)` - для свежей БД, `INSERT OR IGNORE` на `CURRENT_SCHEMA_VERSION`.
- `init_db()` (`src/db/init.py`) - если `schema_version` нет -> `Base.metadata.create_all` + `init_fresh_schema`; иначе -> `run_migrations`.

**Ограничение механизма:** rebuild родительских таблиц (`accounts`, `statements`, `categories`) требует `PRAGMA foreign_keys=OFF` вне `engine.begin()` (внутри транзакции прагма no-op). Текущий цикл этого не поддерживает. Rebuild дочерней таблицы (как в v2) безопасен, потому что на неё никто не ссылается через FK.

## Индексы: сводка

```sql
-- accounts
PRIMARY KEY (account_id)
UNIQUE (bank_name, account_number_masked)

-- statements
PRIMARY KEY (statement_id)
UNIQUE (file_hash)
CREATE INDEX ix_statements_account_id ON statements (account_id)

-- transactions
PRIMARY KEY (transaction_id)
UNIQUE (account_id, transaction_hash)
CREATE INDEX ix_transactions_date          ON transactions (date)
CREATE INDEX ix_transactions_account_date  ON transactions (account_id, date)
CREATE INDEX ix_transactions_statement_id  ON transactions (statement_id)
CREATE INDEX ix_transactions_category_id   ON transactions (category_id)

-- categories
PRIMARY KEY (category_id)
UNIQUE (name, parent_category_id)
CREATE UNIQUE INDEX uq_categories_name_root
    ON categories (name)
    WHERE parent_category_id IS NULL
CREATE INDEX ix_categories_parent_category_id ON categories (parent_category_id)

-- schema_version
PRIMARY KEY (version)
```

## Проверка актуальности (быстро)

```bash
# 1. Версия схемы
sqlite3 data/db/finance.db "SELECT MAX(version) FROM schema_version;"
# ожидаемо: 2

# 2. FK у transactions.statement_id
sqlite3 data/db/finance.db "SELECT sql FROM sqlite_master WHERE name='transactions';"
# ожидаемо: ... FOREIGN KEY(statement_id) REFERENCES statements (statement_id) ON DELETE SET NULL ...

# 3. Отсутствие ix_transactions_is_transfer
sqlite3 data/db/finance.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions';"
# ix_transactions_is_transfer в выводе быть НЕ должно

# 4. Partial unique для корневых категорий
sqlite3 data/db/finance.db "SELECT sql FROM sqlite_master WHERE name='uq_categories_name_root';"
# ожидаемо: ... WHERE parent_category_id IS NULL

# 5. PRAGMA foreign_keys на новом соединении
sqlite3 data/db/finance.db "PRAGMA foreign_keys;"
# ожидаемо: 1 (за счёт глобального listener'а; для CLI sqlite3 может быть 0 - это нормально,
# PRAGMA применяется в Python-приложении через event listener)
```