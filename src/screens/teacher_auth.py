"""Teacher login / registration screens."""
from __future__ import annotations

import streamlit as st

from src.components.footer import footer_dashboard
from src.components.header import header_dashboard
from src.services import auth_service
from src.ui.auth_forms import login_form
from src.ui.feedback import show_error
from src.utils.errors import AppError


def _top_bar() -> None:
    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go back to Home", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            st.session_state["login_type"] = None
            st.rerun()


def teacher_screen_login() -> None:
    _top_bar()
    st.header("Teacher login", text_alignment="center")
    st.space()
    login_form("TEACHER", "teacher")
    st.divider()
    if st.button("New here? Register", type="primary", icon=":material/passkey:", width="stretch"):
        st.session_state.teacher_login_type = "register"
        st.rerun()
    footer_dashboard()


def teacher_screen_register() -> None:
    _top_bar()
    st.header("Register your teacher profile")
    st.space()
    name = st.text_input("Full name", placeholder="Ananya Roy")
    email = st.text_input("Email", placeholder="ananya@college.edu")
    password = st.text_input("Password (min 8 characters)", type="password")
    confirm = st.text_input("Confirm your password", type="password")
    st.divider()

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Register now", icon=":material/passkey:", shortcut="control+enter", width="stretch"):
            try:
                result = auth_service.register_teacher(email, name, password, confirm)
            except AppError as exc:
                show_error(exc)
            else:
                if result.pending_approval:
                    st.success("Account created. An administrator must approve it before you can log in.")
                else:
                    st.success("Account created! You can log in now. (If email confirmation is enabled, confirm your email first.)")
    with b2:
        if st.button("Login Instead", type="primary", icon=":material/passkey:", width="stretch"):
            st.session_state.teacher_login_type = "login"
            st.rerun()
    footer_dashboard()
