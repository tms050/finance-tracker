"""HTML-карточки метрик — замена st.metric с более современным видом."""
from __future__ import annotations

import html

import streamlit as st


def metric_card(
    label: str,
    value: str,
    *,
    variant: str = "neutral",   # "positive" | "negative" | "neutral"
    icon: str | None = None,    # Material Symbols name, напр. "trending_up"
    hint: str | None = None,
) -> None:
    """Метрика в стиле «карточки SaaS»: иконка + uppercase-подпись + значение."""
    icon_html = (
        f'<span data-testid="stIconMaterial" '
        f'style="font-size:16px;opacity:0.65;'
        f'vertical-align:text-bottom;margin-right:5px;">{icon}</span>'
        if icon else ""
    )
    hint_html = (
        f'<div class="metric-hint">{html.escape(hint)}</div>' if hint else ""
    )
    st.markdown(
        f"""
        <div class="metric-card metric-{variant}">
            <div class="metric-label">{icon_html}{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )