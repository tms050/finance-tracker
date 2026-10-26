# `src.categories` - CRUD категорий

Ручное управление категориями. Импорт-специфичная логика (`infer_category_type`, `find_or_create_category`, `import_with_categories`) живёт в `src.importing.categories`. Commit/rollback - за вызывающим (unit-of-work); внутри только `flush()`.

## Публичный API

| Функция | Назначение |
|---|---|
| `get_category(id)` | `Category \| None` |
| `list_categories(*, parent_id=UNSET, type=None)` | Список с фильтрами, сортировка `name ASC, category_id ASC` |
| `create_category(name, type, parent_id=None)` | `ValueError` на дубль `(name, parent_id)` и невалидный `type` |
| `rename_category(id, new_name)` | `ValueError` на дубль / несуществующий id |
| `delete_category(id)` | Транзакции `category_id -> NULL`, затем удаление; `ValueError` на несуществующий |
| `CategoryType` | `Literal["income", "expense", "transfer"]` |

## `list_categories`

| `parent_id` | Что вернёт |
|---|---|
| `UNSET` (default) | все категории |
| `None` | только корневые (`parent_category_id IS NULL`) |
| `int` | только дети указанного родителя |

`type` - опциональный фильтр по типу категории. `UNSET` - из `src._internal.sentinel`.

## `create_category`

- Пустое `name` (после `strip`) -> `ValueError`.
- `type` не в `CATEGORY_TYPES` (`income | expense | transfer`) -> `ValueError` (pre-check до `flush()`, не `IntegrityError`).
- Дубль `(name, parent_id)` -> `ValueError`.

**Тип категории не редактируется.** Отдельного `update_category` нет - только `rename_category`. Если нужно сменить `type`, удалите и создайте заново. Причина: смена `type` у категории с транзакциями сломала бы семантику (income-категория с отрицательными транзакциями и т.п.).

## `rename_category`

- Пустое `new_name` -> `ValueError`.
- Несуществующий `category_id` -> `ValueError`.
- Дубль `(new_name, parent_id)` (того же родителя) -> `ValueError`.

## `delete_category`

- Несуществующий `category_id` -> `ValueError`.
- Транзакции с этой категорией -> `category_id = NULL` (unlink) - явный `UPDATE` в коде, не полагаемся на FK.
- Дети категории -> `parent_category_id = NULL` (становятся корневыми) - это FK-политика `ON DELETE SET NULL` в `models.py`.

## Дерево категорий

- `parent_id` при создании - `None` (корневая) или `int` (ребёнок).
- Глубина не ограничена, но UI-4 работает с плоским списком (`build_category_labels` -> «Родитель / Ребёнок»).
- `merge_categories` (слияние) - бэклог, не входит в v1.

## Известные ограничения

- **`delete_category` на родителе с детьми** может упасть с `IntegrityError` по частичному индексу `uq_categories_name_root`, если у двух корневых категорий окажется одинаковое имя. Сценарий: два ребёнка с одинаковым именем у разных родителей -> удаляем первого родителя (ребёнок стал корневым) -> удаляем второго (его ребёнок тоже стал корневым -> конфликт).
- `list_categories(type=...)` - параметр `type` затеняет builtin; в новом коде лучше `from builtins import type` явно, либо переименовать в `category_type` (breaking change для публичного API - не в v1).