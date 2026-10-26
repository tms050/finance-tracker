# `src.transactions` - CRUD транзакций (B2c)

Ручное добавление, редактирование, удаление, чтение. Не работает со `Statement` (импорт/выписки - в `src.importing`). Commit/rollback - за вызывающим (unit-of-work); внутри только `flush()`.

`UNSET` для partial-update живёт в `src._internal.sentinel` (разделяется с `src.accounts`). 
Импорт: `from src._internal.sentinel import UNSET`.

## Публичный API

### Базовый CRUD

| Функция | Назначение |
|---|---|
| `add_manual_transaction(...)` | Ручное добавление. `source="manual"`, `statement_id=None` |
| `update_transaction(id, **fields)` | Partial update (только переданные поля) |
| `delete_transaction(id)` | Hard delete. `Statement` остаётся |
| `get_transaction(id)` | `Transaction \| None` |
| `list_transactions(**filters)` | Сортировка `date DESC, time DESC NULLS LAST, id DESC` |
| `count_transactions(**filters)` | Тот же набор фильтров, возвращает `int` |
| `DuplicateTransactionError` | Наследник `ValueError`; поля `existing_transaction_id`, `transaction_hash` |

### Агрегации (UI-4)

| Функция | Возвращает | Назначение |
|---|---|---|
| `count_transactions_by_category(session, *, account_id=None)` | `dict[int, int]` | Число транзакций по каждой категории (одним GROUP BY, без N+1) |
| `list_raw_category_groups(session, *, account_id=None)` | `list[RawCategoryGroup]` | Группировка по `raw_category` для bulk-assign |
| `assign_category_to_raw_group(session, *, raw_category, category_id, account_id=None)` | `int` | Массово назначить категорию только тем, у кого `category_id IS NULL`. Возвращает число обновлённых. Не коммитит. |

`RawCategoryGroup(raw_category, total_count, uncategorized_count, total_amount)` - сводка по одной группе. `raw_category=None` - отдельная группа («без сырой категории»); `uncategorized_count=0` - все в группе уже назначены.

## `update_transaction`

**Редактируемые:** `category_id`, `description`, `counterparty_name`, `is_transfer`.

**НЕ редактируемые в B2c:** `date`, `time`, `amount`, `currency`, `authorization_code`. Они входят в `transaction_hash` v1 - для их изменения нужно удалить транзакцию и создать заново (или расширять B1).

`UNSET` -> поле не трогается. `None` для `category_id` / `counterparty_name` -> очищает. `description` нормализуется: пустая строка или строка из пробелов -> `None` (единый sentinel «нет описания» для PDF-импорта и ручного ввода).

### Изменение `description` / `counterparty_name` и хэш

`description` и `counterparty_name` **входят** в `transaction_hash v1`. При update они **не пересчитываются** - хэш остаётся «снимком на момент импорта». Следствия:

- Повторный импорт того же PDF -> `duplicate_statement` (по `file_hash`).
- Импорт другого PDF с **оригинальным** описанием -> `skipped_cross_batch` (хэш совпал с хэшем-снимком).

Т.е. изменение текста не ломает дедупликацию; но если пользователь «перепишет» описание, старый хэш продолжает «бронировать» транзакцию. Это осознанный компромисс - см. `src.importing/README.md` (правило хэша v1).

## `add_manual_transaction`

- Хэш - тем же правилом v1, что и PDF (`prepare_transaction` из B1) -> кросс-источниковая дедупликация работает.
- `currency=None`:
  - `account.currency != "MULTI"` -> подставляется `account.currency`.
  - `account.currency == "MULTI"` -> `ValueError` (`currency_none_multi`).
- `currency` ≠ валюте счёта (`account.currency != "MULTI"`) -> `ValueError`
  (`currency_mismatch`).
- Дубликат `(account_id, transaction_hash)` -> `DuplicateTransactionError` (с полями `existing_transaction_id`, `transaction_hash`).
- Несуществующий `account_id` -> `ValueError`.
- Несуществующий `category_id` -> `ValueError`.
- `account_key` - необязательный бизнес-ключ для хэша (см.`src.importing/README.md`). Default - `str(account_id)`; для стабильности при пересоздании БД передавайте `account.business_key()`.

**Известное ограничение:** валидация `currency` не покрывает случай «MULTI-счёт + неизвестная валюта» (например, `"GBP"`). `prepare_transaction` пропускает такую транзакцию как валидную, и `session.flush()` возвращает `IntegrityError` (CHECK `ck_transactions_currency`). Планируется добавить `ERR_CURRENCY_UNSUPPORTED` в `prepare_transaction` (defense-in-depth для
PDF-пути тоже).

## `delete_transaction`

Hard delete. `Statement`, к которому относилась транзакция, **не удаляется**. `file_hash` остаётся зафиксированным - повторная загрузка того же PDF будет поймана как `duplicate_statement`. Если нужно «переимпортировать» - удалять `Statement` целиком  (см. `src.statements.delete_statement`).

## `list_transactions` / `count_transactions`

Фильтры (все опциональны): `account_id`, `date_from`/`date_to` (включительно), `category_id`, `is_transfer`. `limit=None` - без ограничения; `limit <= 0` -> `ValueError`; `offset < 0` -> `ValueError`.

**Известное ограничение:** `date_from > date_to` не валидируется (вернёт пустой результат). В `src.stats.get_summary` аналогичная проверка уже добавлена - планируется привести к консистентности.

## `count_transactions_by_category` / `list_raw_category_groups` / `assign_category_to_raw_group`

- `account_id=None` - по всем аккаунтам.
- `count_transactions_by_category` не включает `category_id IS NULL` в   результат (для UI-4 «без категории» - отдельная строка).
- `list_raw_category_groups` включает `raw_category=None` (транзакции без «сырой» категории) и группы с `uncategorized_count=0` (уже все назначены). Сортировка: `raw_category NULLS LAST, raw_category ASC`.
- `assign_category_to_raw_group` **не перезаписывает** уже назначенные категории (только `category_id IS NULL`). `raw_category=None` - назначить категорию транзакциям без «сырой» категории. Несуществующий `category_id` -> `ValueError` (pre-check до `UPDATE`).

## Известные ограничения

- `update_transaction` не пересчитывает `transaction_hash` - осознанно (см. раздел выше). `date`/`time`/`amount`/`currency`/`authorization_code` не редактируются.
- `list_transactions`/`count_transactions` не валидируют порядок дат.
- `add_manual_transaction` не валидирует `currency` для `MULTI`-счёта - только для non-MULTI (`IntegrityError` -> нужен `ERR_CURRENCY_UNSUPPORTED`).
- `assign_category_to_raw_group` делает full scan по `raw_category` - для v1 ок, при >10k строк нужен частичный индекс `WHERE raw_category IS NOT NULL`.