"""Teacher login / registration screens."""
from __future__ import annotations

import streamlit as st

from src.components.footer import footer_home
from src.services import auth_service
from src.ui.auth_forms import login_form
from src.ui.feedback import show_error
from src.ui.shell import auth_layout
from src.utils.errors import AppError

_POINTS = ["Take attendance from classroom photos, a voice recording, or both.",
           "Review every result before it is saved. Nothing is recorded until you confirm.",
           "Correct a record at any time. Each correction needs a reason and is kept in the audit trail."]


def teacher_screen_login() -> None:
    with auth_layout("Attendance you can check and trust", _POINTS):
        st.header("Teacher login")
        st.caption("Use the email and password you registered with.")
        login_form("TEACHER", "teacher")
        st.divider()
        st.caption("New to SnapClass?")
        if st.button("Create a teacher account", type="secondary", icon=":material/person_add:", width="stretch"):
            st.session_state.teacher_login_type = "register"
            st.rerun()
    footer_home()


def teacher_screen_register() -> None:
    with auth_layout("Set up your teacher account", _POINTS[:1] + ["An administrator approves new teacher accounts before the first login."]):
        st.header("Register your teacher profile")
        st.caption("All fields are required.")
        name = st.text_input("Full name", placeholder="Ananya Roy", key="reg_t_name", autocomplete="name")
        email = st.text_input("Email", placeholder="ananya@college.edu", key="reg_t_email", autocomplete="email")
        password = st.text_input("Password", type="password", help="At least 8 characters.", key="reg_t_pw", autocomplete="new-password")
        confirm = st.text_input("Confirm password", type="password", key="reg_t_pw2", autocomplete="new-password")
        if st.button("Create account", icon=":material/person_add:", shortcut="control+enter", type="primary", width="stretch"):
            try:
                with st.spinner("Creating your account…"):
                    result = auth_service.register_teacher(email, name, password, confirm)
            except AppError as exc:
                show_error(exc)
            else:
                if result.pending_approval:
                    st.success("Account created. An administrator must approve it before you can log in.")
                else:
                    st.success("Account created. You can log in now. If email confirmation is enabled, confirm your email first.")
        st.divider()
        if st.button("I already have an account", type="tertiary", icon=":material/login:", width="stretch"):
            st.session_state.teacher_login_type = "login"
            st.rerun()
    footer_home()
