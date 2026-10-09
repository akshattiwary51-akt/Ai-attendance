import streamlit as st

LOGO_URL = "https://i.ibb.co/4r5X1FY/apnacollege.png"


def _footer(color: str) -> None:
    st.markdown(
        f"""
        <div style="margin-top:2rem; display:flex; gap:6px; justify-content:center; align-items:center">
        <p style="font-weight:bold; color:{color};"> Created with ❤️ by </p>
        <img src='{LOGO_URL}' style='max-height:25px' />
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer_home():
    _footer("white")


def footer_dashboard():
    _footer("black")
