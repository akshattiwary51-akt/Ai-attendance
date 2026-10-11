"""Teacher dashboard shell (UI only - all logic lives in services)."""
from __future__ import annotations

from functools import partial

import streamlit as st

from src.components.assistant_chat import assistant_chat
from src.components.dialog_create_subject import create_subject_dialog
from src.components.dialog_share_subject import share_subject_dialog
from src.components.footer import footer_home
from src.components.subject_card import subject_card
from src.screens.attendance_flow import teacher_tab_take_attendance
from src.screens.teacher_analytics import teacher_tab_analytics
from src.screens.teacher_auth import teacher_screen_login, teacher_screen_register
from src.screens.teacher_insights import subject_detail_view, teacher_tab_dashboard, teacher_tab_settings, teacher_tab_students
from src.screens.teacher_sessions import teacher_tab_attendance_records
from src.services import subject_service
from src.ui.feedback import show_error
from src.ui.shell import NavItem, sidebar
from src.ui.widgets import empty_state, page_header
from src.utils.errors import AppError

TAB_KEY = "current_teacher_tab"
TAKE = NavItem("take_attendance", "Take attendance", ":material/photo_camera:")
NAV = [
    NavItem("dashboard", "Dashboard", ":material/dashboard:"),
    NavItem("manage_subjects", "Subjects", ":material/menu_book:"),
    NavItem("students", "Students", ":material/groups:"),
    NavItem("attendance_records", "Sessions and records", ":material/fact_check:"),
    NavItem("analytics", "Analytics", ":material/monitoring:"),
    NavItem("assistant", "Assistant", ":material/smart_toy:"),
    NavItem("settings", "Settings", ":material/settings:"),
]


def teacher_screen() -> None:
    if "teacher_data" in st.session_state:
        teacher_dashboard()
    elif st.session_state.get("teacher_login_type", "login") == "login":
        teacher_screen_login()
    else:
        teacher_screen_register()


def teacher_dashboard() -> None:
    teacher = st.session_state.teacher_data
    page = sidebar(role_label="Teacher", name=teacher["name"], items=NAV, state_key=TAB_KEY, cta=TAKE, default="dashboard")
    {"dashboard": teacher_tab_dashboard, "manage_subjects": teacher_tab_manage_subjects, "students": teacher_tab_students,
     "analytics": teacher_tab_analytics, "take_attendance": teacher_tab_take_attendance, "attendance_records": teacher_tab_attendance_records,
     "settings": teacher_tab_settings, "assistant": teacher_tab_assistant}[page]()


def teacher_tab_assistant() -> None:
    page_header("Attendance assistant", "Ask about your subjects, students and sessions in plain language.", ("Teacher", "Assistant"))
    assistant_chat("TEACHER")


def _load_subjects(teacher_id: int) -> list[dict] | None:
    try:
        return subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return None


def _share_button(subject: dict) -> None:
    if st.button(f"Share code: {subject['name']}", key=f"share_{subject['subject_id']}", icon=":material/share:", type="secondary"):
        share_subject_dialog(subject["name"], subject["subject_code"])


def teacher_tab_manage_subjects() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    page_header("Subjects", "The classes you teach, with their share codes and enrolment.", ("Teacher", "Subjects"))
    if st.button("Create a subject", type="primary", icon=":material/add:", key="create_subject"):
        create_subject_dialog(teacher_id)

    subjects = _load_subjects(teacher_id)
    if subjects is None:
        return
    if not subjects:
        empty_state("No subjects found", "Create one with the button above.")
        return
    for sub in subjects:  # every subject is rendered (the original rendered only the last one)
        subject_card(
            name=sub["name"],
            code=sub["subject_code"],
            section=sub["section"],
            stats=[("", "students", sub["total_students"]), ("", "classes", sub["total_classes"])],
            footer_callback=partial(_share_button, sub),
        )
        with st.expander(f"Details: {sub['name']}"):
            subject_detail_view(sub["subject_id"])
