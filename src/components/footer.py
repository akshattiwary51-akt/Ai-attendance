"""Quiet footer for signed-out screens."""
import streamlit as st

LOGO_URL = "https://i.ibb.co/4r5X1FY/apnacollege.png"


def footer_home() -> None:
    st.markdown(
        f'<div style="margin-top:2.5rem;display:flex;gap:.5rem;justify-content:center;align-items:center;color:var(--sc-muted);font-size:.85rem">'
        f'<span>Created by</span><img src="{LOGO_URL}" alt="Apna College" style="max-height:22px"/></div>',
        unsafe_allow_html=True,
    )
