# `src.statements` - чтение и удаление Statement

Не импортирует, не работает с транзакциями CRUD-ом. Commit/rollback - за вызывающим (unit-of-work); внутри только `flush()`.

## Публичный API

| Функция | Назначение |
|---|---|
| `get_statement(id)` | `Statement \| None` |
| `get_statement_by_file_hash(hash)` | `Statement \| None` |
| `list_statements(*, account_id=None, limit=None, offset=0)` | Сортировка `period_start DESC NULLS LAST, statement_id DESC` |
| `delete_statement(id, *, cascade_transactions=True)` | Удалить; см. ниже |
| `DeleteStatementResult` | `statement_id`, `deleted_transactions`, `unlinked_transactions` |

## `list_statements`

Сортировка: `period_start DESC NULLS LAST, statement_id DESC`. NULL `period_start` - в конце.
`limit=None` - без ограничения; `limit <= 0` -> `ValueError`;
`offset < 0` -> `ValueError`.

## `delete_statement`

- `cascade_transactions=True` (default) - удаляет Statement и все его транзакции. `DeleteStatementResult.deleted_transactions` - фактическое число (`result.rowcount`). Основной сценарий: «Сбер перевыпустил PDF -> заменить». После удаления повторный импорт того же `file_hash` пройдёт как обычный новый импорт.

- `cascade_transactions=False` - удаляет только Statement. FK `transactions.statement_id -> ON DELETE SET NULL` обнуляет `statement_id` у транзакций на уровне БД; ORM не вмешивается благодаря `passive_deletes="all"` у `Statement.transactions`.

  **ВНИМАНИЕ:** `transaction_hash` транзакций сохраняется. При повторном импорте того же PDF они уйдут в `skipped_cross_batch` (`status="ok"` со всеми пропущенными). Обычно НЕ то, что нужно. Если нужен настоящий «переимпорт» - используйте `cascade_transactions=True`.

- Несуществующий `statement_id` -> `ValueError`.

## Известные ограничения

- Каскад не трогает `Category` (категории - общие, не привязаны к Statement).
- Подтверждение удаления («вы уверены?») - задача UI, не DB-слоя.
- После `cascade_transactions=False` в БД остаются «висячие» транзакции: `list_statements` их не вернёт, но `list_transactions` и `stats` считают их как обычные.
- **Требование к схеме:** `transactions.statement_id` должен быть `ON DELETE SET NULL`. Если в `models.py` случайно вернётся `CASCADE` (было в v1 до миграции), `delete_statement(cascade_transactions=False)` молча потеряет транзакции. Регрессионный тест обязателен: `test_delete_statement_no_cascade_unlinks_transactions`.