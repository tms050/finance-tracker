## Запуск UI

```bash
streamlit run src/ui/app.py
```

Приложение откроется в браузере (по умолчанию http://localhost:8501).

## Архитектура UI

- `src/ui/app.py` - точка входа: `set_page_config`, sidebar, 4 таба.
- `src/ui/pages/transactions.py` - UI-1: список транзакций + фильтры.
- `src/ui/pages/{upload,stats,categories}.py` - заглушки UI-2/3/4.
- `src/ui/formatters.py` - чистые функции форматирования (без Streamlit и SQLAlchemy), покрыты `tests/ui/test_formatters.py`.

## Сессии SQLAlchemy в UI

- `get_engine()` - долгоживущий объект, инициализируется один раз (внутри `src.db`).
- `get_session()` - короткоживущий, открывается на каждый запрос данных и закрывается сразу после `with`-блока. Не кэшируем сессию в `st.session_state` - иначе получаем утечки, гонки и `DetachedInstanceError` при параллельных ререндерах.
- ORM-объекты не выходят за пределы `with get_session()`: внутри блока материализуем нужные поля в plain `dict`/`list`.  `expire_on_commit=False` защищает только скалярные атрибуты, но не lazy-связи (`tx.category`), поэтому связями не пользуемся вовсе - маппинг категорий делаем отдельным `list_categories(session)`.
- `init_db()` идемпотентен - вызывается на каждом ререндере без побочных эффектов.

### UI-2: загрузка PDF

- `src/ui/pages/upload.py` - двухфазная машина: превью (`A`) -> результат (`B`).
- Все ключи состояния с префиксом `upload_*`, чтобы не пересекаться с UI-1.
- **Tempfile:** создаётся при загрузке (`tempfile.mkstemp`), живёт в `st.session_state["upload_temp_path"]`. Удаляется в `_cleanup_tempfile()`: при «Отмена», «Импортировать ещё файл», загрузке нового файла, успешном импорте, `no_valid_transactions`. **НЕ удаляется** при ошибке импорта - пользователь может повторить. При F5-обновлении страницы tempfile остаётся на диске (известное ограничение v1).
- **`prepare_statement` читает `file_path`** (считает `file_hash` заново) - поэтому tempfile живёт до этого вызова, а не только до превью (расхождение с ТЗ, где сказано «удалять после фазы A»).
- **Auto-switch sidebar** на счёт импорта после успеха - пользователь сразу видит результат в UI-1.
- **`no_valid_transactions`:** бросаем `_NoValidTransactionsError` внутри `with get_session()` -> срабатывает `rollback` -> счёт не создаётся. Rejected показываем в фазе B.
- **MISMATCH / INCOMPLETE / INSUFFICIENT_DATA** не блокируют импорт - это предупреждения уровня парсера.
- **Превью дубликата** без `<N>` транзакций - `count_transactions` не умеет `statement_id`, raw SQL не пишем.
- **Skipped-списки** содержат `original_index` + короткий hash (+ `existing_transaction_id` для cross) - `IntraBatchSkip`/`CrossBatchSkip` не хранят `date`/`amount`/`description`.
- **Парсер:** `from src.parser.sber_parser import SberStatementParser`. Ловим `ValueError` (плохие данные / нет страниц) отдельно от `Exception` (pdfplumber).

### UI-3: статистика и отметка переводов

- `src/ui/pages/stats.py` - сводка (`get_summary`) + редактор переводов.
- `src/ui/components/data_loaders.py` - общий загрузчик транзакций (без Streamlit). Используется UI-1 и UI-3.
- **`st.data_editor`** для отметки переводов: одна редактируемая колонка «Перевод?», кнопка «Сохранить» применяет diff. Матчинг по `ID`, а не по позиции - переживает сортировку.
- **Лимит 200 строк** в редакторе без пагинации: `st.data_editor` плохо дружит с постраничной навигацией (изменения на предыдущей странице теряются). При `total > 200` показываем warning.
- **Atomic save**: всё в одной `with get_session()` -> rollback при любой ошибке.
- **`pending_account_switch`**: смена счёта из UI-2 не пишет в `account_selector` напрямую (StreamlitAPIException), а кладёт «отложенный переключатель», применяемый в `_render_sidebar` **до** `st.selectbox`.
- **`format_amount_for_delta`**: ASCII-минус (не U+2212) в `st.metric(delta=...)` - иначе Streamlit не распознаёт знак и красит отрицательный net зелёным.

### UI-5: ручное добавление транзакции

- `src/ui/pages/add_transaction.py` - форма, доступна из таба «➕ Добавить».
- **Счёт**: локальный `st.selectbox` в форме, независим от sidebar. По умолчанию - текущий из sidebar (если выбран), иначе первый счёт.
- **Сумма**: пользователь вводит **положительное** число в рублях, `st.radio` «Доход / Расход» задаёт знак. Внутри - `format_amount_input_to_kopecks` (Decimal, ROUND_HALF_UP - защита от float-артефактов типа `0.29 * 100 = 28.99…`).
- **Валюта**: для счёта с фиксированной валютой - `st.caption`, в API передаётся `currency=None` (функция подставит из счёта). Для `MULTI` - `st.selectbox`.
- **Время**: опционально, чекбокс «Указать время» активирует `st.time_input`. Если выключен - `time=None`.
- **Категория**: опциональна, первая опция - «- Без категории».
- **Ошибки**:
  - `DuplicateTransactionError` -> `st.error` с `existing_transaction_id`.
  - `ValueError` (currency_mismatch, category_not_found, …) -> `st.error` с текстом.
  - Прочие -> `st.error` + `st.exception` в expander.
- **Flash**: `st.session_state["add_tx_flash"]` + `st.rerun()` - success показывается на следующем рендере, не стирается.
- `source="manual"` проставляется автоматически внутри `add_manual_transaction`.