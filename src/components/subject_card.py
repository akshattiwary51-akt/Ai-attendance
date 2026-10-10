from __future__ import annotations

import streamlit as st

from src.utils.html import esc


def header_html(name, code, section) -> str:
    return (f'<h3>{esc(name)}</h3><p class="sc-sub">Code : <span class="sc-chip">{esc(code)}</span> | Section : {esc(section)}</p>')


def stats_html(stats) -> str:
    return "".join(f'<span class="sc-stat">{esc(i)} <b>{esc(v)}</b> {esc(l)}</span>' for i, l, v in (stats or []))


def subject_card(name, code, section, stats=None, footer_callback=None, body_html: str = ""):
    """One subject card. All dynamic text is HTML-escaped (names are user-supplied); body_html must already be escaped."""
    st.markdown(f'<div class="sc-card">{header_html(name, code, section)}{stats_html(stats)}{body_html}</div>', unsafe_allow_html=True)
    if footer_callback:
        footer_callback()
