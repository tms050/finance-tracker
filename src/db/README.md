# DB Layer (src.db)

Слой доступа к данным (Data Access Layer) для проекта.  
Построен на **SQLAlchemy 2.x** (современный стиль `Mapped` / `mapped_column`) и оптимизирован для работы с **SQLite**.

Пакет инкапсулирует в себе создание подключений, настройку специфичных для SQLite `PRAGMA`, управление транзакциями и декларации моделей.

---

## Требования

* Python 3.10+ (из-за использования `from __future__ import annotations` и синтаксиса `str | None`)
* SQLAlchemy 2.0+
* Встроенный модуль `sqlite3` (идёт в комплекте с Python)

---

## Структура пакета

Пакет разделён на изолированные модули, каждый из которых отвечает за свою зону ответственности:

```text
src/db/
├── __init__.py      # Публичный API пакета (экспорт всего необходимого)
├── base.py          # DeclarativeBase и общие миксины (TimestampMixin)
├── constants.py     # Константы (валюты, источники) и хелперы для SQL
├── engine.py        # Создание Engine, настройка PRAGMA (WAL, FK, timeout)
├── init.py          # Инициализация схемы БД (create_all)
├── models.py        # Декларация таблиц (Account, Statement, Category, Transaction)
└── session.py       # Фабрика сессий и контекстный менеджер get_session
```

---

## Быстрый старт (Quick Start)

### 1. Инициализация базы данных

По умолчанию база создаётся в `data/db/finance.db`. Путь можно переопределить через переменную окружения `FINANCE_DB_PATH`.

```python
from src.db import init_db

# Создаст все таблицы, если их нет
init_db()
```
*После выхода из блока `with get_session()` объекты остаются доступными для чтения (благодаря `expire_on_commit=False`), но не пытайтесь лениво загружать связанные данные (например, `tx.account`), так как сессия уже закрыта*

### 2. Работа с данными

Используйте контекстный менеджер `get_session()`. Он автоматически делает `commit()` при успехе и `rollback()` при исключении.

```python
from datetime import date
from src.db import get_session, Account, Transaction

with get_session() as session:
    # 1. Создаём счёт
    account = Account(
        bank_name="Tinkoff",
        account_name="Main Account",
        account_number_masked="**** 1234",
        currency="RUB"
    )
    session.add(account)
    session.flush()  # Чтобы получить account.account_id без коммита

    # 2. Добавляем транзакцию
    tx = Transaction(
        account_id=account.account_id,
        date=date.today(),
        amount=-1500,  # 15 рублей (в копейках/центах)
        currency="RUB",
        description="Покупка кофе",
        # Хеш должен генерироваться бизнес-логикой до вставки в БД
        transaction_hash="unique_hash_123",
        source="manual"
    )
    session.add(tx)
# Здесь автоматически произошёл session.commit()
```

### Особенности SQLite в проекте

- Включен режим **WAL (Write-Ahead Logging)**: читатели не блокируют писателя.
- Установлен `busy_timeout = 5000`: при конкурентной записи SQLite будет ждать 5 секунд, а не падать с `database is locked`.
- `PRAGMA foreign_keys = ON`: обеспечивает работу каскадных удалений (`ON DELETE CASCADE`).