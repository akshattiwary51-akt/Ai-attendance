"""Shared login form used by all three portals."""
from __future__ import annotations

import streamlit as st

from src.services import auth_service
from src.ui.feedback import show_error
from src.utils.errors import AppError, AuthenticationError
from src.utils.session import login_as


def login_form(role: str, key: str) -> None:
    """Email + password login for *role* (TEACHER / STUDENT / ADMIN). Reruns on success."""
    email = st.text_input("Email", placeholder="you@college.edu", key=f"{key}_email", autocomplete="email")
    password = st.text_input("Password", type="password", placeholder="Enter your password", key=f"{key}_password", autocomplete="current-password")
    if st.button("Log in", icon=":material/login:", shortcut="control+enter", width="stretch", type="primary", key=f"{key}_login"):
        if not email.strip() or not password:
            st.warning("Enter your email and password to log in.")
            return
        try:
            with st.spinner("Logging you in…"):
                payload = auth_service.login(email, password, role)
        except AuthenticationError as exc:
            st.error(exc.user_message)
        except AppError as exc:
            show_error(exc)
        else:
            login_as(payload)
            st.toast("Welcome back")
            st.rerun()
