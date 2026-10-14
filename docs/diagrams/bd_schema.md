# Схема базы данных - v1

Документ описывает структуру БД трекера личных финансов v1.
СУБД: SQLite. ORM: SQLAlchemy. Диаграмма: `docs/diagrams/erd.drawio`.

## Общие принципы

- Денежные суммы хранятся в **целых копейках**, чтобы избежать ошибок округления с плавающей точкой. Поле `amount` знаковое: положительное - доход, отрицательное - расход.
- Все временные метки - `TIMESTAMP` в UTC.
- Даты - `DATE` в ISO-8601 (`YYYY-MM-DD`), время - `TIME` (`HH:MM:SS`).
- Идентификаторы - `INTEGER PRIMARY KEY AUTOINCREMENT`.
- Для полей-перечислений используются `CHECK`-ограничения.
- Дедупликация обеспечивается:
  - на уровне выписок - `UNIQUE(file_hash)`;
  - на уровне транзакций - `UNIQUE(account_id, transaction_hash)`.

## Таблицы

### `accounts`

Банковский счёт пользователя. В v1 - один счёт (Сбер), но структура допускает несколько.

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `account_id` | INTEGER | PK, AUTOINCREMENT | Идентификатор счёта |
| `bank_name` | TEXT | NOT NULL | Название банка |
| `account_name` | TEXT | NOT NULL | Отображаемое имя счёта |
| `account_number_masked` | TEXT | NOT NULL | Маскированный номер счёта |
| `currency` | TEXT | NOT NULL, CHECK (currency IN ('RUB','USD','EUR', 'MULTI')) | Валюта счёта или MULTI для многовалютного счёта |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата создания записи |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата последнего обновления |

Индексы: PK `account_id`.

---

### `statements`

Загруженная выписка. Одна выписка привязана к одному счёту.

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `statement_id` | INTEGER | PK, AUTOINCREMENT | Идентификатор выписки |
| `account_id` | INTEGER | NOT NULL, FK -> accounts.account_id, ON DELETE CASCADE | Счёт, к которому относится выписка |
| `file_name` | TEXT | NOT NULL | Имя загруженного файла |
| `period_start` | DATE | NULL | Начало периода выписки |
| `period_end` | DATE | NULL | Конец периода выписки |
| `file_hash` | TEXT | NOT NULL, UNIQUE | Хэш файла (SHA-256) для дедупликации выписок |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата создания записи |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата последнего обновления |

Индексы: PK `statement_id`; `UNIQUE(file_hash)`; `INDEX(account_id)`.

**Назначение `file_hash`.** Хэш SHA-256 от содержимого PDF. Позволяет распознать повторную загрузку той же выписки и не создавать дубликат. При совпадении система предупреждает пользователя и предлагает отмену, дополнение или перезапись.

---

### `transactions`

Транзакция из выписки или добавленная вручную.

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `transaction_id` | INTEGER | PK, AUTOINCREMENT | Идентификатор транзакции |
| `account_id` | INTEGER | NOT NULL, FK -> accounts.account_id, ON DELETE CASCADE | Счёт транзакции |
| `statement_id` | INTEGER | NULL, FK -> statements.statement_id, ON DELETE CASCADE | Выписка-источник; NULL для ручных и API-транзакций |
| `date` | DATE | NOT NULL | Дата транзакции |
| `time` | TIME | NULL | Время транзакции (может отсутствовать) |
| `amount` | INTEGER | NOT NULL | Сумма в копейках, знаковая |
| `currency` | TEXT | NOT NULL, CHECK (currency IN ('RUB','USD','EUR')) | Фактическая валюта транзакции. Для многовалютного счёта может отличаться от валюты счёта |
| `description` | TEXT | NULL | Описание из выписки |
| `counterparty_name` | TEXT | NULL | Контрагент |
| `category_id` | INTEGER | NULL, FK -> categories.category_id, ON DELETE SET NULL | Категория транзакции |
| `authorization_code` | TEXT | NULL | Код авторизации из выписки. Может отсутствовать у отдельных транзакций |
| `is_transfer` | INTEGER | NOT NULL, DEFAULT 0 \| 1 - перевод самому себе, 0 - обычная. Такие транзакции исключаются из статистики |
| `transaction_hash` | TEXT | NOT NULL | Хэш транзакции для дедупликации. Уникален в рамках счёта: UNIQUE(account_id, transaction_hash) |
| `hash_version` | INTEGER | NOT NULL, DEFAULT 1 | Версия формулы расчёта transaction_hash. Позволяет менять формулу без пересчёта старых записей |
| `source` | TEXT | NOT NULL, CHECK (source IN ('pdf','csv','api','manual')) | Источник транзакции |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата создания записи |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата последнего обновления |

Индексы:
- PK `transaction_id`;
- `UNIQUE(account_id, transaction_hash)`;
- `INDEX(date)`;
- `INDEX(account_id, date)`;
- `INDEX(statement_id)`;
- `INDEX(category_id)`;
- `INDEX(is_transfer)`.

**Назначение `transaction_hash`.** Хэш от набора полей транзакции (дата, сумма, описание/категория, счёт), вычисляемый при парсинге. Позволяет распознать повторно загруженную транзакцию и не создавать дубликат.

---

### `categories`

Справочник категорий. Поддерживает иерархию через `parent_category_id`.

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `category_id` | INTEGER | PK, AUTOINCREMENT | Идентификатор категории |
| `name` | TEXT | NOT NULL | Название категории |
| `type` | TEXT | NOT NULL, CHECK (type IN ('income','expense','transfer')) | Тип категории |
| `parent_category_id` | INTEGER | NULL, FK -> categories.category_id, ON DELETE SET NULL | Родительская категория; NULL для корневой |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата создания записи |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Дата последнего обновления |

Индексы:
- PK `category_id`;
- `UNIQUE(name, parent_category_id)`;
- `INDEX(parent_category_id)`.

**Примечание про `type='transfer'`.** Категории типа «перевод» относятся к переводам самому себе. Признак `is_transfer` в `transactions` устанавливается вручную пользователем и не выводится автоматически из категории.

---

## Связи

| От | К | Тип | ON DELETE |
|---|---|---|---|
| accounts | statements | 1 : M | CASCADE |
| accounts | transactions | 1 : M | CASCADE |
| statements | transactions | 1 : M | CASCADE |
| categories | transactions | 1 : M | SET NULL |
| categories | categories (parent) | 1 : M | SET NULL |

## Дедупликация

- **Выписки.** `UNIQUE(file_hash)`. При совпадении система предупреждает пользователя и предлагает отмену, дополнение или перезапись.
- **Транзакции.** Транзакции. `UNIQUE(account_id, transaction_hash)`. Хэш вычисляется при парсинге и позволяет распознать повторно загруженную транзакцию. Поле `hash_version` позволяет в будущем менять формулу без пересчёта старых записей. При загрузке в v1 всегда используется hash_version = 1. `transaction_hash` вычисляется с использованием полей `account_id`, `date`, `authorization_code`, если последнее поле не null или `account_id`, `date`, `time`.`amount`, `currency`, `description`. При совпадении hash (что практически невозможно) дополнительно сравниваются сопоставимые поля: если они различаются, то транзакция не считается дубликатом.

## Переводы

- `is_transfer = 1` устанавливается вручную для переводов между собственными счетами.
- Такие транзакции исключаются из расчётов общей статистики.
- Переводы третьим лицам учитываются как обычные транзакции.

## Категории

- Пользователь может создавать, редактировать и удалять категории.
- Уникальность: `UNIQUE(name, parent_category_id)`.
- При удалении категории у связанных транзакций `category_id` становится NULL (ON DELETE SET NULL).

## Согласование валют
- Если `accounts.currency = 'MULTI'` - `transactions.currency` для этого счёта может быть любым из разрешенных.
- Если `accounts.currency` - это конкретная валюта, то `transactions.currency` должен совпадать с ней.
- Проверка выполняется на уровне приложения в v1; в БД - только проверка на допустимые значения.