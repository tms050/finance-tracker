# `src.accounts` - CRUD аккаунтов + find_or_create

Commit/rollback - за вызывающим (unit-of-work); внутри только `flush()`.

## Публичный API

| Функция | Назначение |
|---|---|
| `get_account(id)` | `Account \| None` |
| `list_accounts()` | Сортировка `bank_name, account_name, account_id ASC` |
| `create_account(**fields)` | `ValueError` на пустые обязательные поля и невалидные данные |
| `update_account(id, **fields)` | Partial update (`UNSET`-sentinel) |
| `delete_account(id, *, cascade=False)` | См. ниже |
| `find_or_create_account(**fields)` | `(account, created, warnings)` |
| `DeleteAccountResult` | `account_id`, `deleted_statements`, `deleted_transactions` |

**Важно:** функции возвращают ORM-объекты. 

## `create_account`

Обязательные: `bank_name`, `account_name`, `account_number_masked`.
`currency` - default `"RUB"`.

- Строковые поля `strip`-аются; `currency` -> `.upper()`.
- Пустые обязательные -> `ValueError`.
- `currency` не в `ACCOUNT_CURRENCIES` (`RUB | USD | EUR | MULTI`) -> `ValueError`.
- `open_date > close_date` (если оба переданы) -> `ValueError`.
- Дубль `(bank_name, account_number_masked)` -> `ValueError` (pre-check до `flush()`, не `IntegrityError`).
- Для мультивалютного счёта `currency="MULTI"` передавайте **явно**; default `"RUB"` - это однозначно рублёвый счёт.

## `update_account`

`UNSET` (дефолт для каждого поля) -> поле не трогается. `None` для nullable (`fio`, `card_number_masked`, `open_date`, `close_date`) -> очищает.

Валидации при изменении:

| Поле | Проверка | Ошибка |
|---|---|---|
| `bank_name` / `account_name` / `account_number_masked` | не пустые после `strip` | `ValueError` |
| `(bank_name, account_number_masked)` | UNIQUE не нарушен | `ValueError` |
| `currency` | в `ACCOUNT_CURRENCIES` | `ValueError` |
| `currency` (смена != `"MULTI"`) | нет транзакций с другой валютой | `ValueError` |
| `open_date` + `close_date` | `open_date <= close_date` | `ValueError` |

Смена `currency` на `"MULTI"` разрешена всегда. Смена на конкретную валюту -только если у аккаунта нет транзакций в другой валюте.

## `delete_account`

- `cascade=False` (default) - `ValueError`, если у аккаунта есть statements или transactions.
- `cascade=True` - удаляются аккаунт, все его statements и все transactions.
- Возвращает `DeleteAccountResult` с **фактическим** числом удалённых (`result.rowcount`).

Дефолт `False` - операция разрушительнее, чем `delete_statement` (один счёт = вся история). UI должен явно предупредить.

## `find_or_create_account` (B2d)

Бизнес-ключ - `(bank_name, account_number_masked)`, **exact match, case-sensitive**.

- Пустые `bank_name` / `account_number_masked` -> `ValueError`.
- Нашли -> `(existing, False, warnings)`. Атрибуты **не обновляются**; если переданные `currency` / `fio` / `card_number_masked` / `open_date` / `close_date` расходятся с существующими -> `warnings` (по одному на поле).
- Не нашли -> `create_account`, `(new, True, [])`.

**Где вызывать.** UI-слой - **до** `prepare_statement`, если пользователь не выбрал счёт. В B1/B2 `find_or_create` не встроен: `prepare_statement` принимает уже готовый `account_id`.

**Стабильный хэш.** `Account.business_key()` возвращает `"bank:{bank_name}:{account_number_masked}"`. Передавайте его в
`prepare_statement(..., account_key=...)` и `add_manual_transaction(..., account_key=...)`, чтобы хэши оставались стабильными при пересоздании БД (см. `src.importing.README`). Без этого `account_key = str(account_id)` - после `drop tables` хэши поменяются, и повторный импорт тех же PDF создаст дубликаты.

## Известные ограничения

- Бизнес-ключ `(bank_name, account_number_masked)` **case-sensitive**. Если парсер и UI-5 передают разные написания банка (`"Сбербанк"` vs `"Sber"`) - создаются два разных аккаунта на один реальный счёт. Рекомендация: фиксировать `bank_name` как константу в UI и парсере.
- Race при создании: между `SELECT` и `INSERT` теоретически возможен `IntegrityError` по UNIQUE. Для single-writer v1 не актуально; при появлении конкуренции - ретраить `find_or_create` после `IntegrityError`.