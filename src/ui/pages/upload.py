"""UI-2: загрузка PDF-выписки и импорт в БД."""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import streamlit as st

from src.accounts import find_or_create_account
from src.db import get_session
from src.importing import compute_file_hash_from_path, prepare_statement
from src.importing.categories import import_with_categories
from src.parser.sber_parser.sber_pdf import SberStatementParser
from src.statements import delete_statement, get_statement_by_file_hash
from src.ui.components.data_loaders import invalidate_all
from src.ui.formatters import (
    EMPTY,
    format_balance_check,
    format_date,
    format_import_status,
    format_parse_meta,
    format_rejected_row,
    format_skipped_cross,
    format_skipped_intra,
)

BANK_NAME = "Сбербанк"

_STATE_KEYS = (
    "upload_file_id",
    "upload_temp_path",
    "upload_parsed_result",
    "upload_file_hash",
    "upload_duplicate_info",
    "upload_import_result",
    "upload_prepared",
    "upload_import_done",
    "upload_account_info",
    "upload_was_created",
    "upload_account_warnings",
    "upload_import_in_progress",
    "upload_confirm_delete",
)


class _NoValidTransactionsError(Exception):
    def __init__(self, prepared):
        super().__init__("no_valid_transactions")
        self.prepared = prepared


# ---------------------------------------------------------------------------
# Управление состоянием и tempfile
# ---------------------------------------------------------------------------

def _reset_upload_state() -> None:
    _cleanup_tempfile()
    for key in _STATE_KEYS:
        st.session_state.pop(key, None)


def _cleanup_tempfile() -> None:
    path = st.session_state.pop("upload_temp_path", None)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _write_tempfile(uploaded) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="finance_upload_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(uploaded.getbuffer())
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


def _detect_new_file(uploaded) -> bool:
    fid = getattr(uploaded, "file_id", None) or f"{uploaded.name}|{uploaded.size}"
    if st.session_state.get("upload_file_id") != fid:
        st.session_state["upload_file_id"] = fid
        return True
    return False


# ---------------------------------------------------------------------------
# Фаза A: парсинг + превью
# ---------------------------------------------------------------------------

def _process_uploaded_file(uploaded) -> None:
    _cleanup_tempfile()
    st.session_state.pop("upload_parsed_result", None)
    st.session_state.pop("upload_duplicate_info", None)
    st.session_state.pop("upload_file_hash", None)
    st.session_state.pop("upload_confirm_delete", None)

    try:
        path = _write_tempfile(uploaded)
    except Exception as e:
        st.error(f"Не удалось сохранить файл: {type(e).__name__}: {e}")
        return
    st.session_state["upload_temp_path"] = path

    try:
        with st.spinner("Разбор PDF…"):
            parser = SberStatementParser()
            result = parser.parse(path)
    except ValueError as e:
        st.error(f"Не удалось разобрать PDF: {e}")
        _cleanup_tempfile()
        return
    except Exception as e:
        st.error(f"Не удалось открыть PDF: {type(e).__name__}: {e}")
        _cleanup_tempfile()
        return

    try:
        with st.spinner("Вычисление хеша файла…"):
            file_hash = compute_file_hash_from_path(path)
    except Exception as e:
        st.error(f"Не удалось вычислить хеш файла: {type(e).__name__}: {e}")
        _cleanup_tempfile()
        return

    st.session_state["upload_parsed_result"] = result
    st.session_state["upload_file_hash"] = file_hash

    with get_session() as session:
        existing = get_statement_by_file_hash(session, file_hash)
        if existing is not None:
            st.session_state["upload_duplicate_info"] = {
                "statement_id": existing.statement_id,
                "file_name": existing.file_name,
                "period_start": existing.period_start,
                "period_end": existing.period_end,
                "created_at": existing.created_at,
            }


def _render_phase_a() -> None:
    st.markdown("## Загрузка выписки Сбера")
    uploaded = st.file_uploader(
        "Выберите PDF-выписку", type=["pdf"], key="upload_file_widget",
    )

    if uploaded is None:
        if st.session_state.get("upload_file_id") is not None:
            _reset_upload_state()
        return

    if _detect_new_file(uploaded):
        _process_uploaded_file(uploaded)

    parsed = st.session_state.get("upload_parsed_result")
    if parsed is None:
        return

    duplicate = st.session_state.get("upload_duplicate_info")
    if duplicate:
        _render_duplicate_block(duplicate)
        return

    _render_preview(parsed)


def _render_duplicate_block(duplicate: dict) -> None:
    period = (
        f"{format_date(duplicate['period_start'])} – "
        f"{format_date(duplicate['period_end'])}"
    )
    created = (
        duplicate["created_at"].strftime("%d.%m.%Y %H:%M")
        if duplicate.get("created_at") else EMPTY
    )
    st.warning(
        f"Файл уже загружался: **{duplicate['file_name']}**  \n"
        f"Период: {period}  \n"
        f"Загружен: {created}"
    )

    if not st.session_state.get("upload_confirm_delete"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "Удалить старую выписку и импортировать заново",
                type="primary", key="upload_delete_and_reimport",
            ):
                st.session_state["upload_confirm_delete"] = True
                st.rerun()
        with col2:
            if st.button("Отмена", key="upload_cancel_duplicate"):
                _reset_upload_state()
                st.rerun()
        return

    st.error(
        "Будут удалены старая выписка **и все её транзакции**. "
        "Это необратимо. Подтвердить?"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Да, удалить",
            type="primary", key="upload_delete_confirm_yes",
            use_container_width=True,
        ):
            _do_delete_and_reimport(duplicate["statement_id"])
    with col2:
        if st.button(
            "Отмена",
            key="upload_delete_confirm_no",
            use_container_width=True,
        ):
            st.session_state.pop("upload_confirm_delete", None)
            st.rerun()


def _do_delete_and_reimport(statement_id: int) -> None:
    try:
        with st.spinner("Удаление старой выписки…"):
            with get_session() as session:
                delete_statement(
                    session, statement_id, cascade_transactions=True,
                )
    except Exception as e:
        st.error(f"Не удалось удалить выписку: {type(e).__name__}: {e}")
        return

    invalidate_all()
    st.session_state.pop("upload_confirm_delete", None)
    st.session_state.pop("upload_duplicate_info", None)
    st.rerun()


def _render_preview(parsed_result) -> None:
    st.markdown("### Предпросмотр")
    info = parsed_result.statement

    meta = format_parse_meta(info)
    cols = st.columns(2)
    for i, (label, value) in enumerate(meta):
        cols[i % 2].markdown(f"**{label}:** {value}")

    st.divider()

    st.write(f"Транзакций в выписке: **{len(parsed_result.transactions)}**")

    bc = parsed_result.balance_check
    if bc is not None:
        level, message = format_balance_check(bc)
        getattr(st, level)(message)

    if parsed_result.warnings:
        with st.expander(f"Предупреждения парсера ({len(parsed_result.warnings)})"):
            for w in parsed_result.warnings:
                st.write(f"• {w}")

    st.divider()

    if not info.account_number_masked:
        st.error(
            "Не удалось определить номер счёта в выписке. Импорт невозможен."
        )
        return

    if st.button("Импортировать", type="primary", key="upload_do_import"):
        _do_import(parsed_result)


# ---------------------------------------------------------------------------
# Импорт
# ---------------------------------------------------------------------------

def _do_import(parsed_result) -> None:
    if st.session_state.get("upload_import_in_progress"):
        st.warning("Импорт уже выполняется. Подождите.")
        return
    st.session_state["upload_import_in_progress"] = True
    try:
        _do_import_inner(parsed_result)
    finally:
        st.session_state.pop("upload_import_in_progress", None)


def _do_import_inner(parsed_result) -> None:
    temp_path = st.session_state.get("upload_temp_path")
    if not temp_path or not os.path.exists(temp_path):
        st.error("Временный файл не найден. Загрузите выписку заново.")
        _reset_upload_state()
        return

    account_info: dict | None = None
    was_created: bool = False
    acc_warnings: list[str] = []
    prepared = None
    import_result = None

    try:
        with st.spinner("Импорт в БД…"):
            with get_session() as session:
                info = parsed_result.statement
                if not info.account_number_masked:
                    raise ValueError("Не удалось определить номер счёта.")

                account, was_created, acc_warnings = find_or_create_account(
                    session,
                    bank_name=BANK_NAME,
                    account_number_masked=info.account_number_masked,
                    account_name=f"{BANK_NAME} {info.account_number_masked}",
                    currency=info.currency or "RUB",
                    fio=info.fio,
                    card_number_masked=info.card_number_masked,
                    open_date=info.open_date,
                    close_date=info.close_date,
                )
                account_info = {
                    "account_id": account.account_id,
                    "bank_name": account.bank_name,
                    "account_name": account.account_name,
                    "account_number_masked": account.account_number_masked,
                }

                prepared = prepare_statement(
                    parsed_result,
                    account_id=account.account_id,
                    account_currency=account.currency,
                    file_path=temp_path,
                    account_key=account.business_key(),
                )
                if not prepared.transactions_to_insert:
                    raise _NoValidTransactionsError(prepared)

                import_result = import_with_categories(
                    session, prepared, auto_create_categories=True,
                )
    except _NoValidTransactionsError as e:
        st.session_state["upload_prepared"] = e.prepared
        st.session_state["upload_import_result"] = None
        st.session_state["upload_account_info"] = account_info
        st.session_state["upload_was_created"] = was_created
        st.session_state["upload_account_warnings"] = acc_warnings
        st.session_state["upload_import_done"] = True
        _cleanup_tempfile()
        st.rerun()
        return
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка импорта: {type(e).__name__}: {e}")
        with st.expander("Детали ошибки"):
            st.exception(e)
        return

    st.session_state["upload_prepared"] = prepared
    st.session_state["upload_import_result"] = import_result
    st.session_state["upload_account_info"] = account_info
    st.session_state["upload_was_created"] = was_created
    st.session_state["upload_account_warnings"] = acc_warnings
    st.session_state["upload_import_done"] = True

    _cleanup_tempfile()

    assert account_info is not None
    st.session_state["pending_account_switch"] = account_info["account_id"]
    st.session_state["tx_page"] = 0

    # Импорт затронул accounts, transactions и (возможно) categories.
    invalidate_all()

    st.rerun()


# ---------------------------------------------------------------------------
# Фаза B: результат импорта
# ---------------------------------------------------------------------------

def _render_phase_b() -> None:
    import_result = st.session_state.get("upload_import_result")
    prepared = st.session_state.get("upload_prepared")
    account_info = st.session_state.get("upload_account_info")
    was_created = st.session_state.get("upload_was_created", False)
    acc_warnings = st.session_state.get("upload_account_warnings") or []

    if import_result is None:
        st.warning(
            "Нет валидных транзакций для импорта. Счёт не создан."
        )
        _render_balance_check(prepared)
        _render_rejected(prepared)
        _render_reset_button()
        return

    level, message = format_import_status(
        import_result.status,
        warnings_count=len(import_result.warnings),
    )
    getattr(st, level)(message)

    _render_balance_check(prepared)

    if import_result.status == "ok":
        if account_info:
            if was_created:
                st.info(
                    f"Создан новый счёт: **{account_info['account_name']}** "
                    f"(id={account_info['account_id']})"
                )
            else:
                st.info(
                    f"Использован существующий счёт: "
                    f"**{account_info['account_name']}** "
                    f"(id={account_info['account_id']})"
                )

        st.write(
            f"Вставлено транзакций: **{len(import_result.inserted_transactions)}**"
        )

        _render_skipped_intra(import_result.skipped_intra_batch)
        _render_skipped_cross(import_result.skipped_cross_batch)

        if import_result.created_categories:
            st.info(
                f"Создано категорий: {len(import_result.created_categories)}"
            )

        if import_result.warnings:
            with st.expander(
                f"Предупреждения импорта ({len(import_result.warnings)})"
            ):
                for w in import_result.warnings:
                    st.write(f"• {w}")

    elif import_result.status == "duplicate_statement":
        st.warning(
            f"Файл уже был импортирован (statement_id={import_result.statement_id}). "
            f"Удалите старую выписку, чтобы импортировать заново."
        )

    if prepared is not None and prepared.warnings:
        with st.expander(
            f"Предупреждения парсера и подготовки ({len(prepared.warnings)})"
        ):
            for w in prepared.warnings:
                st.write(f"• {w}")

    _render_rejected(prepared)

    if acc_warnings:
        with st.expander(f"Предупреждения по счёту ({len(acc_warnings)})"):
            for w in acc_warnings:
                st.write(f"• {w}")

    _render_reset_button()


def _render_balance_check(prepared) -> None:
    if prepared is None:
        return
    bc = getattr(prepared, "balance_check", None)
    if bc is None:
        return
    level, message = format_balance_check(bc)
    getattr(st, level)(message)


def _render_skipped_intra(skipped) -> None:
    if not skipped:
        return
    with st.expander(f"Пропущено внутри батча: {len(skipped)}"):
        for s in skipped:
            st.write(f"• {format_skipped_intra(s)}")


def _render_skipped_cross(skipped) -> None:
    if not skipped:
        return
    with st.expander(f"Пропущено (уже есть в БД): {len(skipped)}"):
        for s in skipped:
            st.write(f"• {format_skipped_cross(s)}")


def _render_rejected(prepared) -> None:
    if prepared is None or not prepared.rejected:
        return
    rows = [
        {"№": r.original_index + 1, **format_rejected_row(r)}
        for r in prepared.rejected
    ]
    with st.expander(f"Отклонённые транзакции ({len(rows)})"):
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )


def _render_reset_button() -> None:
    if st.button(
        "Импортировать ещё файл",
        icon=":material/upload:",
        type="primary",
        key="upload_reset",
    ):
        _reset_upload_state()
        st.rerun()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def render() -> None:
    if st.session_state.get("upload_import_done"):
        _render_phase_b()
    else:
        _render_phase_a()