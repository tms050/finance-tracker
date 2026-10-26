"""UI-4: справочник категорий, назначение категорий транзакциям, bulk-assign."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from src.categories import (
    create_category,
    delete_category,
    list_categories,
    rename_category,
)
from src.db import get_session
from src.transactions import (
    assign_category_to_raw_group,
    count_transactions_by_category,
    list_raw_category_groups,
    update_transaction,
)
from src.ui.components.data_loaders import (
    invalidate_categories,
    invalidate_transactions,
    load_transactions,
)
from src.ui.formatters import (
    EMPTY,
    build_category_labels,
    format_amount,
    format_category_parents,
    format_category_type_ru,
    format_optional_text,
    format_date,
)

_CATEGORY_TYPES = ["expense", "income", "transfer"]
_TX_LIMIT = 200

# Sentinel для selectbox «Создать новую…».
_CREATE_SENTINEL: str = "__create__"


def render(account_id: int | None) -> None:
    if "cats_flash" in st.session_state:
        st.success(st.session_state.pop("cats_flash"))

    st.markdown("## Категории")
    tab_catalog, tab_assign, tab_bulk = st.tabs([
        "Справочник",
        "Назначить транзакцию",
        "Массовое назначение",
    ])
    with tab_catalog:
        _render_catalog()
    with tab_assign:
        _render_single_assign(account_id)
    with tab_bulk:
        _render_bulk_assign(account_id)


# =========================================================================
# Загрузка
# =========================================================================

def _load_categories_dto() -> list[SimpleNamespace]:
    with get_session() as session:
        return [
            SimpleNamespace(
                category_id=c.category_id,
                name=c.name,
                type=c.type,
                parent_category_id=c.parent_category_id,
            )
            for c in list_categories(session)
        ]


def _load_counts() -> dict[int, int]:
    with get_session() as session:
        return count_transactions_by_category(session)


def _flash(message: str) -> None:
    st.session_state["cats_flash"] = message


# =========================================================================
# Tab 1: Справочник
# =========================================================================

def _render_catalog() -> None:
    categories = _load_categories_dto()
    counts = _load_counts()

    if categories:
        _render_catalog_table(categories, counts)
    else:
        st.info("Категорий пока нет - создайте первую ниже.")

    st.divider()
    st.markdown("### Создать категорию")
    _render_create_form(categories)

    st.divider()
    st.markdown("### Переименовать")
    _render_rename_form(categories)

    st.divider()
    st.markdown("### Удалить")
    _render_delete_form(categories, counts)


def _render_catalog_table(categories, counts) -> None:
    parents = format_category_parents(categories)
    data = [
        {
            "Название": c.name,
            "Тип": format_category_type_ru(c.type),
            "Родитель": parents.get(c.category_id, EMPTY),
            "Транзакций": counts.get(c.category_id, 0),
        }
        for c in categories
    ]
    st.dataframe(
        pd.DataFrame(data),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Название": st.column_config.TextColumn("Название", width="large"),
            "Тип": st.column_config.TextColumn("Тип", width="small"),
            "Родитель": st.column_config.TextColumn("Родитель", width="medium"),
            "Транзакций": st.column_config.NumberColumn(
                "Транзакций", format="%d", width="small",
            ),
        },
    )


def _render_create_form(categories) -> None:
    labels = build_category_labels(categories)
    parent_options: list[int | None] = [None] + [
        c.category_id for c in categories if c.type != "transfer"
    ]

    def _fmt_parent(pid: int | None) -> str:
        if pid is None:
            return "Без родителя"
        return labels.get(pid, f"#{pid}")

    with st.form("cat_create_form", clear_on_submit=True):
        name = st.text_input("Название", key="cat_create_name")
        cat_type = st.selectbox(
            "Тип", options=_CATEGORY_TYPES,
            format_func=format_category_type_ru,
            key="cat_create_type",
        )
        parent_id = st.selectbox(
            "Родитель", options=parent_options,
            format_func=_fmt_parent, key="cat_create_parent",
        )
        submitted = st.form_submit_button("Создать", type="primary")

    if not submitted:
        return

    name = name.strip()
    if not name:
        st.error("Название не может быть пустым.")
        return
    try:
        with st.spinner("Создание категории…"):
            with get_session() as session:
                create_category(session, name, cat_type, parent_id=parent_id)
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка создания: {type(e).__name__}: {e}")
        return
    invalidate_categories()
    _flash(f"Категория «{name}» создана.")
    st.rerun()


def _render_rename_form(categories) -> None:
    if not categories:
        st.caption("Нет категорий для переименования.")
        return

    labels = build_category_labels(categories)
    options = [c.category_id for c in categories]

    with st.form("cat_rename_form"):
        cid = st.selectbox(
            "Категория", options=options,
            format_func=lambda x: labels.get(x, f"#{x}"),
            key="cat_rename_id",
        )
        st.caption(f"Сейчас: **{labels.get(cid, f'#{cid}')}**")
        new_name = st.text_input("Новое название", key="cat_rename_name")
        submitted = st.form_submit_button("Переименовать", type="primary")

    if not submitted:
        return

    new_name = new_name.strip()
    if not new_name:
        st.error("Название не может быть пустым.")
        return
    try:
        with st.spinner("Переименование…"):
            with get_session() as session:
                rename_category(session, cid, new_name)
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка переименования: {type(e).__name__}: {e}")
        return
    invalidate_categories()
    _flash(f"Категория переименована в «{new_name}».")
    st.rerun()


def _render_delete_form(categories, counts) -> None:
    if not categories:
        st.caption("Нет категорий для удаления.")
        return

    labels = build_category_labels(categories)
    options = [c.category_id for c in categories]

    cid = st.selectbox(
        "Категория для удаления", options=options,
        format_func=lambda x: labels.get(x, f"#{x}"),
        key="cat_delete_id",
    )
    n_tx = counts.get(cid, 0)
    children = [c for c in categories if c.parent_category_id == cid]

    if n_tx:
        st.warning(f"У {n_tx} транзакций категория станет NULL.")
    if children:
        st.warning(
            f"Это родитель для {len(children)} категорий - "
            f"они станут корневыми."
        )

    confirmed = st.checkbox(
        "Я понимаю последствия", key="cat_delete_confirm",
    )
    if st.button(
        "Удалить",
        icon=":material/delete:",
        type="primary",
        disabled=not confirmed,
        key="cat_delete_btn",
    ):
        try:
            with st.spinner("Удаление категории…"):
                with get_session() as session:
                    delete_category(session, cid)
        except ValueError as e:
            st.error(f"Ошибка: {e}")
            return
        except Exception as e:
            st.error(f"Ошибка удаления: {type(e).__name__}: {e}")
            return
        invalidate_categories()
        invalidate_transactions()
        _flash("Категория удалена.")
        st.rerun()


# =========================================================================
# Tab 2: Назначить транзакцию
# =========================================================================

def _render_single_assign(account_id: int | None) -> None:
    st.caption(
        "Назначить категорию одной транзакции. Работает только по выбранному "
        "счёту (или по всем, если в sidebar выбрано «Все счета»)."
    )

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input(
            "С даты", value=date.today().replace(day=1),
            key="uc05_date_from",
        )
    with col2:
        date_to = st.date_input(
            "По дату", value=date.today(), key="uc05_date_to",
        )

    filters: dict = {}
    if account_id is not None:
        filters["account_id"] = account_id
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to

    categories = _load_categories_dto()
    if not categories:
        st.info("Сначала создайте хотя бы одну категорию в «Справочнике».")
        return
    cat_labels = build_category_labels(categories)

    with st.spinner("Загрузка транзакций…"):
        raw, total, _ = load_transactions(filters, page=0, page_size=_TX_LIMIT)
    if not raw:
        st.info("Транзакций по фильтру нет.")
        return
    if total > _TX_LIMIT:
        st.warning(f"Показаны первые {_TX_LIMIT} из {total}. Уточните период.")

    tx_by_id = {r["transaction_id"]: r for r in raw}
    tx_options = list(tx_by_id)

    def _fmt_tx(tx_id: int) -> str:
        r = tx_by_id[tx_id]
        current_cat = (
            cat_labels.get(r["category_id"], f"#{r['category_id']}")
            if r["category_id"] else "- без категории"
        )
        return (
            f"#{tx_id} · {format_date(r['date'])} · "
            f"{format_amount(r['amount'])} · "
            f"категория: {current_cat} · "
            f"{format_optional_text(r['description'], max_len=40)}"
        )

    cat_options: list[int | None] = [None] + [c.category_id for c in categories]

    def _fmt_cat(cid: int | None) -> str:
        if cid is None:
            return "- Без категории"
        return cat_labels.get(cid, f"#{cid}")

    with st.form("uc05_assign_form"):
        tx_id = st.selectbox(
            "Транзакция", options=tx_options,
            format_func=_fmt_tx, key="uc05_tx",
        )
        new_cat = st.selectbox(
            "Категория", options=cat_options,
            format_func=_fmt_cat, key="uc05_cat",
        )
        submitted = st.form_submit_button("Применить", type="primary")

    if not submitted:
        return

    try:
        with st.spinner("Обновление категории…"):
            with get_session() as session:
                update_transaction(session, tx_id, category_id=new_cat)
    except Exception as e:
        st.error(f"Ошибка: {type(e).__name__}: {e}")
        return
    invalidate_transactions()
    _flash("Категория обновлена.")
    st.rerun()


# =========================================================================
# Tab 3: Bulk-assign по raw_category
# =========================================================================

def _render_bulk_assign(account_id: int | None) -> None:
    st.caption(
        "Назначает категорию всем транзакциям с выбранным raw_category, "
        "у которых категории ещё нет. Уже назначенные не перезаписываются. "
        "Транзакции с raw_category=None (без «сырой» категории) "
        "назначаются только вручную во вкладке «Назначить транзакцию»."
    )

    with get_session() as session:
        groups = list_raw_category_groups(session, account_id=account_id)
    categories = _load_categories_dto()

    if not groups:
        st.info("Транзакций нет.")
        return

    _render_raw_groups_table(groups)

    assignable = [
        g for g in groups
        if g.raw_category and g.uncategorized_count > 0
    ]
    if not assignable:
        st.success("Все транзакции с raw_category уже имеют категорию.")
        return

    st.write(f"Доступно для назначения: **{len(assignable)}** raw_category.")

    labels_map = {
        g.raw_category: f"{g.raw_category} ({g.uncategorized_count} без категории)"
        for g in assignable
    }
    selected_raw = st.multiselect(
        "Что назначить", options=list(labels_map.keys()),
        format_func=lambda x: labels_map[x],
        key="bulk_selected",
    )

    if not categories:
        st.info("Сначала создайте хотя бы одну категорию в «Справочнике».")
        return
    cat_labels = build_category_labels(categories)

    cat_options: list[int | None | str] = (
        [None]
        + [c.category_id for c in categories]
        + [_CREATE_SENTINEL]
    )

    def _fmt_cat(cid: int | None | str) -> str:
        if cid is None:
            return "- Не назначать"
        if cid == _CREATE_SENTINEL:
            return "Создать новую…"
        return cat_labels.get(cid, f"#{cid}")

    selected_cat = st.selectbox(
        "Категория для назначения",
        options=cat_options,
        format_func=_fmt_cat,
        key="bulk_category",
    )

    if selected_cat == _CREATE_SENTINEL:
        _render_create_and_assign(selected_raw, account_id)
    else:
        _render_apply_only(selected_raw, selected_cat, account_id)


def _render_raw_groups_table(groups) -> None:
    data = [
        {
            "raw_category": g.raw_category if g.raw_category else EMPTY,
            "Всего": g.total_count,
            "Без категории": g.uncategorized_count,
            "Сумма": format_amount(g.total_amount),
        }
        for g in groups
    ]
    st.dataframe(
        pd.DataFrame(data),
        use_container_width=True,
        hide_index=True,
        column_config={
            "raw_category": st.column_config.TextColumn(
                "raw_category", width="medium",
            ),
            "Всего": st.column_config.NumberColumn("Всего", format="%d", width="small"),
            "Без категории": st.column_config.NumberColumn(
                "Без категории", format="%d", width="small",
            ),
            "Сумма": st.column_config.TextColumn("Сумма", width="small"),
        },
    )


def _render_apply_only(
    selected_raw: list[str],
    category_id: int | None,
    account_id: int | None,
) -> None:
    if not selected_raw:
        st.caption("Выберите хотя бы один raw_category.")
        return
    if category_id is None:
        st.caption("Выберите категорию для назначения.")
        return

    if not st.button(
        "Применить",
        icon=":material/check:",
        type="primary",
        key="bulk_apply_btn",
    ):
        return

    updated = 0
    try:
        with st.spinner("Назначение категорий…"):
            with get_session() as session:
                for rc in selected_raw:
                    try:
                        updated += assign_category_to_raw_group(
                            session,
                            raw_category=rc,
                            category_id=category_id,
                            account_id=account_id,
                        )
                    except Exception as e:
                        raise RuntimeError(
                            f"raw_category={rc!r}: {type(e).__name__}: {e}"
                        ) from e
    except Exception as e:
        st.error(f"Ошибка: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return

    invalidate_transactions()
    _flash(f"Обновлено транзакций: {updated}.")
    st.rerun()


def _render_create_and_assign(
    selected_raw: list[str],
    account_id: int | None,
) -> None:
    if not selected_raw:
        st.caption("Выберите хотя бы один raw_category.")
        return

    default_name = selected_raw[0] if len(selected_raw) == 1 else ""
    with st.form("bulk_create_and_assign"):
        new_name = st.text_input(
            "Название новой категории", value=default_name,
            key="bulk_new_name",
        )
        new_type = st.selectbox(
            "Тип", options=_CATEGORY_TYPES,
            format_func=format_category_type_ru,
            key="bulk_new_type",
        )
        submitted = st.form_submit_button(
            "Создать и назначить", type="primary",
        )

    if not submitted:
        return

    new_name = new_name.strip()
    if not new_name:
        st.error("Название не может быть пустым.")
        return

    updated = 0
    try:
        with st.spinner("Создание и назначение…"):
            with get_session() as session:
                new_cat = create_category(session, new_name, new_type)
                for rc in selected_raw:
                    try:
                        updated += assign_category_to_raw_group(
                            session,
                            raw_category=rc,
                            category_id=new_cat.category_id,
                            account_id=account_id,
                        )
                    except Exception as e:
                        raise RuntimeError(
                            f"raw_category={rc!r}: {type(e).__name__}: {e}"
                        ) from e
    except ValueError as e:
        st.error(f"Ошибка: {e}")
        return
    except Exception as e:
        st.error(f"Ошибка: {e}")
        with st.expander("Детали"):
            st.exception(e)
        return

    invalidate_categories()
    invalidate_transactions()
    _flash(
        f"Создана категория «{new_name}», обновлено транзакций: {updated}."
    )
    st.rerun()