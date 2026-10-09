"""Shared login form used by all three portals."""
from __future__ import annotations

import streamlit as st

from src.services import auth_service
from src.ui.feedback import show_error
from src.utils.errors import AppError, AuthenticationError
from src.utils.session import login_as


def login_form(role: str, key: str) -> None:
    """Email + password login for *role* (TEACHER / STUDENT / ADMIN). Reruns on success."""
    email = st.text_input("Email", placeholder="you@college.edu", key=f"{key}_email")
    password = st.text_input("Password", type="password", placeholder="Enter password", key=f"{key}_password")
    if st.button("Login", icon=":material/passkey:", shortcut="control+enter", width="stretch", key=f"{key}_login"):
        try:
            payload = auth_service.login(email, password, role)
        except AuthenticationError as exc:
            st.error(exc.user_message)
        except AppError as exc:
            show_error(exc)
        else:
            login_as(payload)
            st.toast("Welcome back!", icon="👋")
            st.rerun()
