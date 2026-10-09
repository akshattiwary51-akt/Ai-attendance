"""Streamlit session bridge: stores the login, supplies the DB principal, refreshes tokens, logs out."""
from __future__ import annotations

import streamlit as st

from src.security.principal import Principal, set_provider
from src.services import auth_service
from src.utils.errors import AppError
from src.utils.logging import get_logger

log = get_logger(__name__)
_KEEP_ON_LOGOUT = frozenset({"login_type"})
_ROLE_KEY = {"ADMIN": "admin_data", "TEACHER": "teacher_data", "STUDENT": "student_data"}


def login_as(payload: dict) -> None:
    """Store a successful ``auth_service.login`` result."""
    auth = payload["auth"]
    st.session_state.auth = auth
    st.session_state.is_logged_in = True
    st.session_state.user_role = auth["role"].lower()
    st.session_state[_ROLE_KEY[auth["role"]]] = payload["user"]


def principal_from_session() -> Principal | None:
    """Current principal from session state; refreshes the access token shortly before it expires."""
    auth = st.session_state.get("auth")
    if not auth:
        return None
    if auth_service.needs_refresh(auth["expires_at"]):
        try:
            auth = auth_service.refresh(auth)
        except AppError:
            log.info("session_refresh_failed")
            return None
        st.session_state.auth = auth
    return Principal(auth["user_id"], auth["access_token"], auth["role"], auth.get("teacher_id"), auth.get("student_id"))


def install() -> None:
    set_provider(principal_from_session)


def session_expired() -> bool:
    """True when somebody is logged in but their token can no longer be used."""
    return bool(st.session_state.get("auth")) and principal_from_session() is None


def logout() -> None:
    """Revoke the server session (best effort) and drop ALL per-user state except the portal choice."""
    auth = st.session_state.get("auth") or {}
    auth_service.logout(auth.get("access_token"))
    for key in list(st.session_state.keys()):
        if key not in _KEEP_ON_LOGOUT:
            del st.session_state[key]
