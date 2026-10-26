# finance-tracker

Трекер личных финансов с парсингом банковских выписок.

## Цель

Локальный single-user инструмент для контроля личных финансов:
загрузить PDF-выписку Сбербанка, распарсить в SQLite, посмотреть список/статистику, назначить категории, при необходимости добавить транзакцию вручную.

**Статус:** v1 (MVP) - работает end-to-end; финальная шлифовка UI.

## Быстрый старт

```bash
git clone <repo-url> && cd finance-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/ui/app.py
```

Откройте http://localhost:8501, загрузите PDF-выписку Сбербанка во вкладке «Загрузка». БД создаётся автоматически в `data/db/finance.db` (путь можно переопределить переменной окружения `FINANCE_DB_PATH`).

## Возможности (v1)

- Загрузка PDF через UI (Streamlit file uploader) и парсинг выписок Сбербанка.
- Сохранение в SQLite через SQLAlchemy 2.x. `amount` - целые копейки (`int`), никогда `float`.
- Дедупликация двух уровней:
  - `file_hash` (SHA-256 от содержимого файла) -> повторная загрузка того же PDF ловится как `duplicate_statement`;
  - `transaction_hash` (SHA-256 от полей транзакции) -> `UNIQUE(account_id, transaction_hash)`, кросс-батчевые дубликаты как `skipped_cross_batch`.
- Список транзакций с фильтрами (счёт, даты, категория, тип) и пагинацией.
- Отметка транзакций как «перевод» - исключаются из `income` / `expense` / `count` и учитываются отдельно в `transfer_count`.
- Сводка (`get_summary`): `income`, `expense`, `net`, `count`, `transfer_count`, с валидацией `date_from <= date_to`.
- Категоризация: ручное назначение (`update_transaction`) и bulk-assign по «сырой» категории из PDF (`assign_category_to_raw_group`, UI-4).
- CRUD категорий и аккаунтов через UI.
- Ручное добавление транзакций (`source="manual"`, `statement_id=None`), с тем же правилом хэша, что и для PDF.
- Мультивалютные счета (`RUB` | `USD` | `EUR` | `MULTI`); транзакция в валюте, не совпадающей с валютой счёта, отклоняется на `prepare_transaction`.

## Стек

- Python 3.10+ (по факту 3.14)
- SQLAlchemy 2.x (`Mapped` / `mapped_column`)
- SQLite (WAL, `busy_timeout=5000`, `PRAGMA foreign_keys=ON`)
- Streamlit ≥ 1.30 - UI
- pandas ≥ 2.0 - только для UI (`st.data_editor`, отображение), не для бэкенда: `amount` - `int` копеек
- pdfplumber - парсинг PDF
- pytest - тесты бэкенда и чистых UI-функций

## Структура репозитория

```text
finance-tracker/
├── README.md
├── requirements.txt
├── data/
│   ├── raw/                    # PDF-выписки (не в git)
│   └── db/                     # SQLite-файл (не в git)
├── src/
│   ├── _internal/              # UNSET-sentinel (общий для пакетов)
│   ├── accounts/               # CRUD аккаунтов + find_or_create
│   ├── categories/             # CRUD категорий
│   ├── db/                     # engine, PRAGMA, миграции, модели
│   ├── importing/              # prepare / import_to_db / categories
│   ├── parser/sber_parser/     # SberStatementParser
│   ├── statements/             # чтение / удаление Statement
│   ├── stats/                  # get_summary
│   ├── transactions/           # CRUD + агрегации
│   └── ui/                     # Streamlit (app.py, formatters, pages/)
└── tests/
    ├── _internal/
    ├── db/
    ├── importing/
    ├── parser/
    ├── transactions/
    └── ui/
```

## Документация

Пакетные README:

- `src/db/README.md` - Engine, PRAGMA, миграции, модели.
- `src/accounts/README.md` - CRUD аккаунтов, `find_or_create`.
- `src/categories/README.md` - CRUD категорий.
- `src/importing/README.md` - подготовка и импорт, правило хэша v1, дедупликация.
- `src/statements/README.md` - удаление `Statement` (cascade / unlink).
- `src/stats/README.md` - семантика `get_summary`.
- `src/transactions/README.md` - CRUD, агрегации, `add_manual_transaction`.
- `src/parser/sber_parser/README.md` - обзор парсера, быстрый старт.
- `src/parser/sber_parser/API.md` - контракт публичного API (классы, инварианты, статусы).

## Требования к выписке

- PDF с текстовым слоем (не скан/фото). Проверка: откройте файл и попробуйте выделить текст.
- Выписка Сбербанка, оформленная через приложение или веб-версию (формат на 01.10.2024; при изменении вёрстки банка парсер свалится в `default layout` и выдаст предупреждения).
- Один PDF = одна выписка по одному счёту, период произвольный.

## Известные ограничения (v1)

- Только Сбербанк. Другие банки - в планах.
- `counterparty_name` извлекается по известным паттернам; на необычных описаниях может быть `None`.
- Сверка баланса ловит арифметические расхождения, но не ошибки распознавания, если они внутренне согласованы.
- PDF без текстового слоя (сканы) не поддерживаются.
- Пагинация только в UI-1 (список транзакций). UI-3 (сводка) и UI-4 (категории) работают с лимитом `EDIT_LIMIT=200` без пагинации.
- `transaction_hash` не пересчитывается при `update_transaction` - осознанно: `date` / `time` / `amount` / `currency` / `auth` не редактируются. `description` / `counterparty_name` входят в хэш v1 и остаются «снимком на момент импорта».
- `get_summary` не разделяет валюты. Для мультивалютных сценариев фильтруйте по `account_id` (один счёт = одна валюта).
- Бизнес-ключ аккаунта `(bank_name, account_number_masked)` - case-sensitive. UI должен фиксировать `bank_name` как константу, иначе `"Сбербанк"` и `"Sber"` создадут два счёта на один реальный.
- bulk-assign (UI-4) - только по `raw_category`, только одна категория за раз.
- UI-2 (загрузка): временный файл не удаляется при F5-обновлении страницы.
- `delete_statement(cascade_transactions=False)` оставляет транзакции с `statement_id=NULL`; при повторном импорте того же PDF они уйдут в `skipped_cross_batch`. Обычно не то, что нужно.

## Roadmap (после v1)

- Парсеры других банков (Tinkoff, Альфа).
- Графики в UI-3 (по месяцам, по категориям).
- CSV-экспорт транзакций.
- Мультивалютные агрегаты (с нормализацией по курсу ЦБ на дату).
- Слияние категорий (`merge_categories`).
- Разбивка переводов на «in / out».

## Приватность

Приложение работает локально. Выписки, база и транзакции не покидают вашу машину. Телеметрии и внешних API нет.