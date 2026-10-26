# `src.db` — слой доступа к данным

Построен на SQLAlchemy 2.x (`Mapped` / `mapped_column`) и оптимизирован
для локального SQLite. Инкапсулирует создание `Engine`, `PRAGMA`, миграции
схемы, декларации моделей и жизненный цикл сессии.

**Правило №1:** внешний код работает **только** через `src.db.__init__`.
Внутренности пакета (`src.db.engine`, `src.db.session`, ...) — приватные.

## Требования

- Python 3.10+
- SQLAlchemy 2.0+
- `sqlite3` (встроен в Python)

## Структура пакета

```text
src/db/
├── __init__.py      # публичный API пакета
├── base.py          # DeclarativeBase + TimestampMixin
├── constants.py     # CURRENT_HASH_VERSION, SOURCES, sql_in_list, ...
├── engine.py        # make_engine / get_engine + PRAGMA-listener
├── init.py          # init_db: create_all ИЛИ run_migrations
├── migrations.py    # schema_version, MIGRATIONS, run_migrations
├── models.py        # Account, Statement, Category, Transaction
└── session.py       # get_session() + make_session_factory(engine)
```

## Публичный API

```python
init_db(engine=None)          # идемпотентен, зовём в main() на каждом rerun
get_engine() -> Engine        # singleton
make_engine(url=None, *, echo=False) -> Engine  # для тестов
get_session() -> ContextManager[Session]        # commit/rollback/close
make_session_factory(engine) -> sessionmaker    # для тестов / инъекции

Base, TimestampMixin
Account, Category, Statement, Transaction

CURRENT_SCHEMA_VERSION, get_schema_version(engine), run_migrations(engine)
```

`SessionLocal` удалён — сессии создаются лениво внутри `get_session()`,
импорт `src.db` больше не создаёт файлов БД. Если нужна фабрика снаружи
(тесты) — `make_session_factory(engine)`.

## Быстрый старт

```python
from src.db import init_db, get_session
from src.accounts import create_account
from src.transactions import add_manual_transaction
from src.importing import compute_transaction_hash  # для ручного add

init_db()  # идемпотентно, на каждом запуске

with get_session() as session:
    account = create_account(
        session,
        bank_name="Tinkoff",
        account_name="Main Account",
        account_number_masked="**** 1234",
        currency="RUB",
    )

with get_session() as session:
    add_manual_transaction(
        session,
        account_id=account.account_id,
        date=date.today(),
        amount=-1500,                  # копейки: −15.00 ₽
        description="Покупка кофе",
        # хэш считается внутри add_manual_transaction через prepare_transaction
    )
```

> **НЕ создавайте** `Transaction(...)` / `Account(...)` руками — это обходит
> валидацию, pre-check UNIQUE, нормализацию description и вычисление
> `transaction_hash`. Только `create_account` / `add_manual_transaction` /
> `import_prepared_statement`.

## Инварианты сессии

- **Короткоживущая.** Одна сессия — один `with get_session()`. Никогда не
  храните `Session` в `st.session_state`.
- **Не вызывайте `session.commit()` вручную** внутри `with get_session()`.
  Контекстный менеджер сам делает `commit` при успехе и `rollback` при
  исключении. Ручной commit ломает атомарность unit-of-work.
- **ORM-объекты не выходят за `with`.** Внутри материализуйте в `dict` /
  DTO бэкенда. `expire_on_commit=False` спасает только скалярные поля,
  уже загруженные в объект — но не lazy-связи (`tx.account`,
  `account.statements`): при закрытой сессии они бросят
  `DetachedInstanceError`.
- **`init_db()` идемпотентен** — вызывайте в начале `main()` на каждом
  rerun Streamlit. Внутри: `create_all()` для свежей БД, `run_migrations()`
  для существующей.

## Настройки SQLite (`_apply_sqlite_pragmas`)

Слушатель на классе `Engine` — применяется ко всем engines, включая
тестовые.

| PRAGMA / параметр | Значение | Зачем |
| :--- | :--- | :--- |
| `PRAGMA foreign_keys` | `ON` | `ON DELETE CASCADE` / `SET NULL` без этого не работают |
| `PRAGMA journal_mode` | `WAL` | читатели не блокируют писателя |
| `PRAGMA synchronous` | `NORMAL` | WAL + NORMAL = безопасно и быстрее, чем FULL |
| `PRAGMA busy_timeout` | `5000` | ждать 5 сек при блокировке вместо `database is locked` |
| `connect_args["isolation_level"]` | `"IMMEDIATE"` | транзакция сразу берёт write-lock, меньше дедлоков |
| `pool_pre_ping` | `True` | страховка для долгоживущего Streamlit-процесса |

> После `PRAGMA journal_mode=WAL` обязательно `cursor.fetchone()` —
> иначе накопленный результат + `IMMEDIATE` могут дать
> `cannot commit transaction - SQL statements in progress`.

Для `sqlite:///:memory:` WAL тихо игнорируется (возвращается `"memory"`) —
это ожидаемо в тестах.

## Миграции

`CURRENT_SCHEMA_VERSION` (`migrations.py`) — единственный источник правды
о версии схемы. При изменении `models.py`:

1. Увеличить `CURRENT_SCHEMA_VERSION`.
2. Добавить функцию `_migrate_to_vN(conn)` в `MIGRATIONS = {N: ...}`.
3. Прогнать `run_migrations(engine)` — применит всё до `N`.

`run_migrations`:

- `current > CURRENT` → `RuntimeError` («БД новее кода»), миграция не
  выполняется.
- Каждая миграция + `_record_version` — в одной транзакции. Падение
  миграции не оставит БД в промежуточном состоянии.
- `_check_foreign_keys(conn)` после каждой миграции: `PRAGMA foreign_key_check` — падает, если остались битые FK.
- `init_fresh_schema` пишет `CURRENT_SCHEMA_VERSION` через `INSERT OR IGNORE` —
  функция идемпотентна (можно звать повторно, если `schema_version` уже
  существует, но пустая).

**Не поддерживается:** rebuild родительских таблиц (нужен
`PRAGMA foreign_keys=OFF` вне `engine.begin()`). Для v1 неактуально —
пересобираем только `transactions`.

## Модели (кратко)

| Модель | Ключевое |
| :--- | :--- |
| `Account` | `UNIQUE (bank_name, account_number_masked)`; `CHECK currency IN (RUB, USD, EUR, MULTI)`; `business_key()` → `"bank:{bank_name}:{account_number_masked}"` |
| `Statement` | `UNIQUE file_hash`; FK `account_id` `ON DELETE CASCADE` |
| `Category` | `UNIQUE (name, parent_category_id)` + частичный `UNIQUE` по корневым; FK `parent_category_id` `ON DELETE SET NULL` |
| `Transaction` | `amount` — int-копейки (никогда `float`); `is_transfer` — int `0/1`; `transaction_hash` + `hash_version` UNIQUE по `(account_id, hash)`; `category_id` `ON DELETE SET NULL`; `statement_id` `ON DELETE SET NULL` |

## Известные ограничения v1

- Один процесс, один пользователь, без авторизации.
- SQLite-специфично: `isolation_level="IMMEDIATE"`, WAL, `PRAGMA foreign_keys` через listener. Для другой СУБД потребуется переработка
  `engine.py` и, возможно, миграций.
- `init_fresh_schema` не защищает от «древней» схемы без `schema_version`:
  если таблицы есть, а `schema_version` нет — `create_all()` их не тронет,
  `init_fresh_schema` запишет `CURRENT_SCHEMA_VERSION` как есть. Риск для
  v1 отсутствует (нет таких БД), но при появлении — добавить проверку.
- Race между `_get_current_version` и `run_migrations`: два процесса
  одновременно могут начать одну миграцию. Для single-user локального
  приложения неактуально.