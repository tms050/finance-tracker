"""Лёгкий механизм миграций схемы SQLite.

Идея:
  - Таблица schema_version хранит применённые версии.
  - MIGRATIONS - реестр функций {версия: callable}.
  - run_migrations() применяет всё, что новее текущей версии.

Ограничения:
  - Только single-process
  - Нет downgrade: откат версии приложения требует ручного отката БД.
  - Rebuild РОДИТЕЛЬСКИХ таблиц (accounts/statements/categories) требует
    PRAGMA foreign_keys=OFF снаружи engine.begin(); текущий цикл это не
    поддерживает.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

CURRENT_SCHEMA_VERSION: int = 2

# ---------------------------------------------------------------------------
# Миграции
# ---------------------------------------------------------------------------

def _migrate_to_v2(conn: Connection) -> None:
    """transactions.statement_id: ON DELETE CASCADE -> ON DELETE SET NULL.

    SQLite не поддерживает смену FK через ALTER TABLE - пересобираем таблицу.
    """
    conn.execute(text("""
        CREATE TABLE transactions__new (
            transaction_id      INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            account_id          INTEGER NOT NULL,
            statement_id        INTEGER,
            date                DATE    NOT NULL,
            time                TIME,
            amount              INTEGER NOT NULL,
            currency            VARCHAR NOT NULL,
            description         TEXT,
            counterparty_name   VARCHAR,
            category_id         INTEGER,
            authorization_code  VARCHAR,
            raw_category        TEXT,
            is_transfer         INTEGER DEFAULT '0' NOT NULL,
            transaction_hash    VARCHAR NOT NULL,
            hash_version        INTEGER DEFAULT '1' NOT NULL,
            source              VARCHAR NOT NULL,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT uq_transactions_account_hash
                UNIQUE (account_id, transaction_hash),
            CONSTRAINT ck_transactions_currency
                CHECK (currency IN ('RUB', 'USD', 'EUR')),
            CONSTRAINT ck_transactions_source
                CHECK (source IN ('pdf', 'csv', 'api', 'manual')),
            CONSTRAINT ck_transactions_is_transfer
                CHECK (is_transfer IN (0, 1)),
            CONSTRAINT ck_transactions_hash_version
                CHECK (hash_version >= 1),
            FOREIGN KEY (account_id)   REFERENCES accounts (account_id)
                ON DELETE CASCADE,
            FOREIGN KEY (statement_id) REFERENCES statements (statement_id)
                ON DELETE SET NULL,
            FOREIGN KEY (category_id)  REFERENCES categories (category_id)
                ON DELETE SET NULL
        )
    """))
    conn.execute(text("""
        INSERT INTO transactions__new (
            transaction_id, account_id, statement_id, date, time, amount,
            currency, description, counterparty_name, category_id,
            authorization_code, raw_category, is_transfer,
            transaction_hash, hash_version, source, created_at, updated_at
        )
        SELECT
            transaction_id, account_id, statement_id, date, time, amount,
            currency, description, counterparty_name, category_id,
            authorization_code, raw_category, is_transfer,
            transaction_hash, hash_version, source, created_at, updated_at
        FROM transactions
    """))
    conn.execute(text("DROP TABLE transactions"))
    conn.execute(text("ALTER TABLE transactions__new RENAME TO transactions"))

    # Индексы создаём после RENAME, чтобы имена были «как в модели».
    conn.execute(text("CREATE INDEX ix_transactions_date         ON transactions (date)"))
    conn.execute(text("CREATE INDEX ix_transactions_account_date ON transactions (account_id, date)"))
    conn.execute(text("CREATE INDEX ix_transactions_statement_id ON transactions (statement_id)"))
    conn.execute(text("CREATE INDEX ix_transactions_category_id  ON transactions (category_id)"))

MIGRATIONS: dict[int, Callable[[Connection], None]] = {
    2: _migrate_to_v2,
}


# ---------------------------------------------------------------------------
# Инфраструктура
# ---------------------------------------------------------------------------

def _ensure_version_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))


def _get_current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        ).scalar_one()


def _record_version(conn: Connection, version: int) -> None:
    conn.execute(
        text("INSERT INTO schema_version (version) VALUES (:v)"),
        {"v": version},
    )


def _check_foreign_keys(conn: Connection) -> None:
    """PRAGMA foreign_key_check: пустой результат = целостность FK в порядке."""
    violations = conn.execute(text("PRAGMA foreign_key_check")).all()
    if violations:
        preview = "; ".join(str(row) for row in violations[:5])
        raise RuntimeError(
            f"foreign_key_check failed: {len(violations)} row(s) "
            f"with broken FK references. Sample: {preview}"
        )


def init_fresh_schema(engine: Engine) -> None:
    """Для свежей БД: записать CURRENT_SCHEMA_VERSION после create_all().
    Идемпотентна: повторный вызов не падает (INSERT OR IGNORE).
    """
    _ensure_version_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (:v)"
            ),
            {"v": CURRENT_SCHEMA_VERSION},
        )


def run_migrations(engine: Engine) -> None:
    """Применить все неприменённые миграции до CURRENT_SCHEMA_VERSION.
    """
    _ensure_version_table(engine)
    current = _get_current_version(engine)

    if current > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"БД новее кода: schema_version={current}, "
            f"code supports up to {CURRENT_SCHEMA_VERSION}. "
            f"Обновите приложение."
        )

    if current == CURRENT_SCHEMA_VERSION:
        return

    for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(
                f"Нет миграции для версии {version}. "
                f"Добавьте её в MIGRATIONS."
            )
        with engine.begin() as conn:
            migration(conn)
            _check_foreign_keys(conn)   # NEW: гарантия целостности ФК
            _record_version(conn, version)


def get_schema_version(engine: Engine) -> int:
    _ensure_version_table(engine)
    return _get_current_version(engine)