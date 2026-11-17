import html
from pathlib import Path
from typing import Any, List, Optional
import streamlit as st


_CACHED_CSS: Optional[str] = None


def inject_styles() -> None:
    # load and inject custom css (cached in memory)
    global _CACHED_CSS
    if _CACHED_CSS is None:
        css_path = Path(__file__).resolve().parent.parent / "styles.css"
        if css_path.exists():
            with open(css_path, "r", encoding="utf-8") as file:
                _CACHED_CSS = file.read()
        else:
            _CACHED_CSS = ""
    if _CACHED_CSS:
        st.markdown(f"<style>{_CACHED_CSS}</style>", unsafe_allow_html=True)


def render_metric_card(
    label: str,
    value: str,
    caption: str = "",
    accent: str = "default",
) -> str:
    # generate html for a styled metric card
    accent_class = ""
    if accent == "owes":
        accent_class = "owes-accent"
    elif accent in ("paid", "settled"):
        accent_class = "paid-accent"
    elif accent == "primary":
        accent_class = "primary-accent"

    safe_label = html.escape(label)
    safe_value = html.escape(value)
    caption_html = (
        f'<div class="metric-caption">{html.escape(caption)}</div>'
        if caption
        else ""
    )

    return (
        f'<div class="metric-card {accent_class}">'
        f'<div class="metric-label">{safe_label}</div>'
        f'<div class="metric-value">{safe_value}</div>'
        f"{caption_html}"
        f"</div>"
    )


def render_metrics_row(cards_html: List[str]) -> None:
    # display a row of styled metric cards
    combined = "".join(cards_html)
    st.markdown(
        f'<div class="metrics-grid">{combined}</div>',
        unsafe_allow_html=True,
    )


def render_banner(text: str, banner_type: str = "info") -> None:
    # display a styled status banner
    safe_text = html.escape(text)
    st.markdown(
        f'<div class="banner-box {banner_type}">{safe_text}</div>',
        unsafe_allow_html=True,
    )


def render_badge(text: str, badge_type: str = "info") -> str:
    # return html string for a pill badge
    safe_text = html.escape(text)
    return f'<span class="badge badge-{badge_type}">{safe_text}</span>'


def render_table(
    headers: List[str],
    rows: List[List[Any]],
    alignments: Optional[List[str]] = None,
) -> None:
    # render a clean styled html table
    if not rows:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-title">No records to display</div>'
            '<div class="empty-state-desc">Try adjusting your filters</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    align_list = alignments or ["left"] * len(headers)

    header_cols = "".join(
        f'<th style="text-align: {align_list[i]};">{html.escape(h)}</th>'
        for i, h in enumerate(headers)
    )

    body_rows = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            align = align_list[i] if i < len(align_list) else "left"
            if isinstance(cell, str) and ("<div" in cell or "<span" in cell or "<br" in cell or "<b" in cell or "<a" in cell or "<p" in cell):
                cell_html = cell
            else:
                cell_html = html.escape(str(cell))
            cells.append(f'<td style="text-align: {align};">{cell_html}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = (
        '<div class="custom-table-wrapper">'
        '<table class="custom-table">'
        f"<thead><tr>{header_cols}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)
