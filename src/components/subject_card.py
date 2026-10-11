from __future__ import annotations

import streamlit as st

from src.utils.html import esc


def header_html(name, code, section) -> str:
    return (f'<h3>{esc(name)}</h3><div class="sc-card-meta">Code <span class="sc-chip">{esc(code)}</span> &nbsp; Section {esc(section)}</div>')


def stats_html(stats) -> str:
    """stats: (icon, label, value) tuples. The icon is ignored; the numbers are what matters."""
    return "".join(f'<span class="sc-stat"><b>{esc(v)}</b> {esc(l)}</span>' for _, l, v in (stats or []))


def subject_card(name, code, section, stats=None, footer_callback=None, body_html: str = ""):
    """One subject card. All dynamic text is HTML-escaped (names are user-supplied); body_html must already be escaped."""
    st.markdown(f'<div class="sc-card">{header_html(name, code, section)}{stats_html(stats)}{body_html}</div>', unsafe_allow_html=True)
    if footer_callback:
        footer_callback()
