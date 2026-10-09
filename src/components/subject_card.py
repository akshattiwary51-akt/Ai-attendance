from __future__ import annotations

import streamlit as st

from src.utils.html import esc


def subject_card(name, code, section, stats=None, footer_callback=None):
    """Render one subject card. All dynamic text is HTML-escaped (names are user-supplied)."""
    html = f"""
        <div style="background:white; border-left: 8px solid #EB459E; padding:25px; border-radius: 20px; border: 1px solid black; margin-bottom:20px;">
        <h3 style="margin:0; color: #1e293b; font-size: 1.5rem">{esc(name)}</h3>
        <p style="color:#64748b; margin:10px 0;">Code : <span style="background:#E0E3FF; color:#5865F2; padding:2px 8px; border-radius:5px;">{esc(code)}</span> | Section : {esc(section)}</p>
        """
    if stats:
        html += '<div style="display:flex; gap:8px; flex-wrap:wrap;">'
        for icon, label, value in stats:
            html += (
                f'<div style="background:#EB459E10; color:#1e293b; padding:5px 12px; border-radius:12px; font-size:0.9rem">'
                f"{esc(icon)} <b>{esc(value)}</b> {esc(label)}</div>"
            )
        html += "</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
    if footer_callback:
        footer_callback()
