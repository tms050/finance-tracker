# `src.stats` - агрегаты (UC-03)

Тонкий модуль. Только `SELECT ... SUM/COUNT` через SQLAlchemy.

## `get_summary(*, account_id=None, date_from=None, date_to=None, category_id=None) -> Summary`

Возвращает `Summary(income, expense, net, count, transfer_count)`.

### Семантика

| Поле | Что это |
|---|---|
| `income` | `sum(amount)` для `amount > 0` и `is_transfer == 0`. `>= 0`. |
| `expense` | `-sum(amount)` для `amount < 0` и `is_transfer == 0`. `>= 0`. |
| `net` | `income - expense`. Может быть отрицательным. |
| `count` | Число транзакций с `is_transfer == 0` (включая `amount=0`). |
| `transfer_count` | Число транзакций с `is_transfer == 1`. |

`is_transfer` - `Integer NOT NULL` (0/1), а не `bool` (см. модель). Сравнение через `== 0 / == 1` - идиоматично для Integer и работает с индексом.

### Derived properties

| Property | Что это |
|---|---|
| `total_count` | `count + transfer_count`. Согласовано с `count_transactions(session)` без фильтров. |
| `has_data` | `total_count > 0`. Удобно для empty-state в UI-3. |

`count` **не** включает переводы. Если нужен «всего операций» - это `total_count`, а не `count`.

### Инварианты

- Переводы **исключены** из `income` / `expense` / `net` / `count`, учтены в `transfer_count`.
- Пустые данные -> `Summary(0, 0, 0, 0, 0)` (не `None`).
- `is_transfer` **не** входит в фильтры функции - это агрегат по определению (переводы отделены от доходов/расходов).
- Даты **включительно** (`date_from <= date <= date_to`).
- `date_from > date_to` -> `ValueError` (до запроса, без тихих нулей).

### `Raises`

- `ValueError` - `date_from > date_to`.

### `category_id` × `transfer_count` - ловушка

`category_id` применяется ко **всем** агрегатам, включая `transfer_count`. Обычно переводы не категоризируются - но если у перевода выставлен `category_id`, он попадёт в `transfer_count` при фильтре по этой категории.

В UI-3 фильтра по категории нет (сознательно, чтобы не путать `transfer_count`) - см. `Известные ограничения v1`. Но публичный API это позволяет; учитывайте при добавлении фич.

### Известное ограничение v1

Агрегат **не разделяет валюты**. Если у пользователя несколько счетов в разных валютах, `income` / `expense` суммируют разные валюты как int. Решение - фильтровать по `account_id` (один счёт = одна валюта). Мультивалютные агрегаты - в бэклоге.

### Тесты (обязательные)

- Пустая таблица -> `Summary(0,0,0,0,0)`.
- `amount=0`, non-transfer -> `count=1`, `income=expense=net=0`.
- `amount=0`, `is_transfer=1` -> `count=0`, `transfer_count=1`.
- Только переводы -> `income=expense=count=0`.
- `date_from > date_to` -> `ValueError`.
- `date_from == date_to` -> OK (не ошибка).
- `category_id` + перевод с этой категорией -> фиксирует поведение ловушки.
- `total_count == count_transactions(session)` без фильтров.
- Отрицательный `net` (`income=100, expense=300` -> `net=-200`).

## Чего здесь нет (бэклог)

- `get_monthly_summary` - для графиков.
- `count_by_category` / `sum_by_category` - для пирога «расходы по категориям».
- `get_balance_series` - динамика остатка.
- `transfer_in` / `transfer_out` / `transfer_sum` - переводы «в одну сторону», сумма переводов.
- Мультивалютные агрегаты с нормализацией по курсу.