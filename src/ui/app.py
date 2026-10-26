"""Streamlit-приложение Finance Tracker - точка входа."""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

st.set_page_config(
    page_title="Finance Tracker",
    layout="wide",
    page_icon="💰",
    initial_sidebar_state="expanded",
)

from src.db import init_db
from src.ui.formatters import format_account_label
from src.ui.components.data_loaders import (
    invalidate_all,
    load_accounts_cached,
)
from src.ui.pages import accounts as accounts_page
from src.ui.pages import categories as categories_page
from src.ui.pages import stats, transfers, transactions, upload
from src.ui.pages import add_transaction


# ---------------------------------------------------------------------------
# Инфраструктура
# ---------------------------------------------------------------------------

def _bootstrap() -> bool:
    try:
        init_db()
        return True
    except Exception as exc:
        st.error(f"Не удалось инициализировать БД: {type(exc).__name__}: {exc}")
        with st.expander("Детали"):
            st.exception(exc)
        return False


def _inject_css() -> None:
    css_path = _PROJECT_ROOT / "assets" / "style.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )


def _run_with_error_boundary(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        st.error(f"Ошибка: {type(exc).__name__}: {exc}")
        with st.expander("Детали"):
            st.exception(exc)


def _require_account(render_fn, account_id, accounts) -> None:
    if not accounts:
        st.info(
            "База пуста. Создайте счёт во вкладке «Счета» или загрузите "
            "PDF-выписку во вкладке «Загрузка»."
        )
        return
    _run_with_error_boundary(render_fn, account_id=account_id)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar(accounts: list[dict]) -> int | None:
    with st.sidebar:
        st.markdown("### Finance Tracker")
        st.divider()

        if not accounts:
            st.caption("Нет счетов в базе")
            st.info(
                "Создайте счёт во вкладке **«Счета»** или загрузите PDF "
                "во вкладке **«Загрузка»**."
            )
            st.divider()
            if st.button("Обновить страницу", use_container_width=True):
                invalidate_all()
                st.rerun()
            return None

        labels: dict[int | None, str] = {None: "Все счета"}
        for a in accounts:
            labels[a["account_id"]] = format_account_label(
                a["bank_name"], a["account_name"],
                a["account_number_masked"], is_closed=a["is_closed"],
            )

        option_ids: list[int | None] = [None] + [a["account_id"] for a in accounts]

        if "account_selector" not in st.session_state:
            st.session_state["account_selector"] = accounts[0]["account_id"]

        if st.session_state["account_selector"] not in option_ids:
            st.session_state["account_selector"] = accounts[0]["account_id"]

        if "pending_account_switch" in st.session_state:
            pending = st.session_state.pop("pending_account_switch")
            if pending in option_ids:
                st.session_state["account_selector"] = pending
                st.session_state.pop("add_tx_account", None)
            else:
                st.toast("Не удалось переключить счёт - возможно, он был удалён")

        selected = st.selectbox(
            "Счёт",
            options=option_ids,
            index=option_ids.index(st.session_state["account_selector"]),
            format_func=lambda x: labels[x],
            key="account_selector",
        )

        if st.session_state.get("current_account_id") != selected:
            st.session_state["current_account_id"] = selected
            st.session_state["tx_page"] = 0
            st.session_state.pop("add_tx_account", None)

        st.divider()
        if st.button("Обновить страницу", use_container_width=True):
            invalidate_all()
            st.rerun()

        st.caption(f"v1 · {len(accounts)} счёт(ов)")
        return st.session_state["current_account_id"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_transactions() -> None:
    _require_account(
        transactions.render,
        st.session_state.get("current_account_id"),
        load_accounts_cached(),
    )


def page_add() -> None:
    _require_account(
        add_transaction.render,
        st.session_state.get("current_account_id"),
        load_accounts_cached(),
    )


def page_upload() -> None:
    _run_with_error_boundary(upload.render)


def page_stats() -> None:
    _require_account(
        stats.render,
        st.session_state.get("current_account_id"),
        load_accounts_cached(),
    )


def page_transfers() -> None:
    _require_account(
        transfers.render,
        st.session_state.get("current_account_id"),
        load_accounts_cached(),
    )


def page_categories() -> None:
    _require_account(
        categories_page.render,
        st.session_state.get("current_account_id"),
        load_accounts_cached(),
    )


def page_accounts() -> None:
    _run_with_error_boundary(accounts_page.render)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not _bootstrap():
        st.stop()

    _inject_css()

    accounts = load_accounts_cached()
    st.session_state["current_account_id"] = _render_sidebar(accounts)

    pages = [
        st.Page(page_transactions, title="Транзакции",
                icon=":material/receipt_long:", default=True),
        st.Page(page_add,         title="Добавить",   icon=":material/add_circle:"),
        st.Page(page_upload,      title="Загрузка",   icon=":material/upload_file:"),
        st.Page(page_stats,       title="Статистика", icon=":material/bar_chart:"),
        st.Page(page_transfers,   title="Переводы",   icon=":material/swap_horiz:"),
        st.Page(page_categories,  title="Категории",  icon=":material/label:"),
        st.Page(page_accounts,    title="Счета",      icon=":material/account_balance:"),
    ]

    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()