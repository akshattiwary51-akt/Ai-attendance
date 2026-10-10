"""SnapClass entry point."""
import os

from dotenv import load_dotenv
import streamlit as st

from src.components.dialog_auto_enroll import auto_enroll_dialog
from src.screens.admin_screen import admin_screen
from src.screens.home_screen import home_screen
from src.screens.student_screen import student_screen
from src.screens.teacher_screen import teacher_screen
from src.utils import session


def main() -> None:
    if st.runtime.exists() and "PYTEST_CURRENT_TEST" not in os.environ:
        load_dotenv()
    st.set_page_config(
        page_title="SnapClass - Making Attendance faster using AI",
        page_icon="https://i.ibb.co/YTYGn5qV/logo.png",
    )
    session.install()  # DB access always uses the logged-in user's token (RLS), resolved from session state
    st.session_state.setdefault("login_type", None)

    if session.session_expired():
        session.logout()
        st.warning("Your session expired. Please log in again.")

    match st.session_state["login_type"]:
        case "teacher":
            teacher_screen()
        case "student":
            student_screen()
        case "admin":
            admin_screen()
        case _:
            home_screen()

    join_code = st.query_params.get("join-code")
    if join_code:
        if st.session_state.login_type != "student":
            st.session_state.login_type = "student"
            st.rerun()
        if st.session_state.get("is_logged_in") and st.session_state.get("user_role") == "student":
            auto_enroll_dialog(join_code)


main()
