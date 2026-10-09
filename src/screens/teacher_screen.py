"""Teacher dashboard (UI only - all logic lives in services)."""
from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

from src.components.dialog_add_photo import add_photos_dialog
from src.components.dialog_attendance_results import attendance_result_dialog
from src.components.dialog_create_subject import create_subject_dialog
from src.components.dialog_share_subject import share_subject_dialog
from src.components.dialog_voice_attendance import voice_attendance_dialog
from src.components.footer import footer_dashboard
from src.components.header import header_dashboard
from src.components.subject_card import subject_card
from src.screens.teacher_auth import teacher_screen_login, teacher_screen_register
from src.screens.teacher_sessions import teacher_tab_attendance_records
from src.services import attendance_service, enrollment_service, recognition_service, session_service, subject_service
from src.ui.base_layout import style_background_dashboard, style_base_layout
from src.ui.feedback import show_error
from src.utils.errors import AppError
from src.utils.session import logout

TABS = {
    "take_attendance": ("Take Attendance", ":material/ar_on_you:"),
    "manage_subjects": ("Manage Subjects", ":material/book_ribbon:"),
    "attendance_records": ("Attendance Records", ":material/cards_stack:"),
}


def teacher_screen() -> None:
    style_background_dashboard()
    style_base_layout()

    if "teacher_data" in st.session_state:
        teacher_dashboard()
    elif st.session_state.get("teacher_login_type", "login") == "login":
        teacher_screen_login()
    else:
        teacher_screen_register()


def teacher_dashboard() -> None:
    teacher = st.session_state.teacher_data
    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"Welcome, {teacher['name']}")
        if st.button("Logout", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            logout()
            st.rerun()

    st.space()
    st.session_state.setdefault("current_teacher_tab", "take_attendance")
    for col, (key, (label, icon)) in zip(st.columns(len(TABS)), TABS.items()):
        with col:
            active = st.session_state.current_teacher_tab == key
            if st.button(label, type="primary" if active else "tertiary", width="stretch", icon=icon, key=f"tab_{key}"):
                st.session_state.current_teacher_tab = key
                st.rerun()
    st.divider()

    {"take_attendance": teacher_tab_take_attendance, "manage_subjects": teacher_tab_manage_subjects, "attendance_records": teacher_tab_attendance_records}[
        st.session_state.current_teacher_tab
    ]()
    footer_dashboard()


def _load_subjects(teacher_id: int) -> list[dict] | None:
    try:
        return subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return None


def teacher_tab_take_attendance() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Take AI Attendance")
    st.session_state.setdefault("attendance_images", [])

    subjects = _load_subjects(teacher_id)
    if subjects is None:
        return
    if not subjects:
        st.warning("You haven't created any subjects yet! Please create one to begin!")
        return

    options = {f"{s['name']} - {s['subject_code']}": s["subject_id"] for s in subjects}
    col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
    with col1:
        label = st.selectbox("Select Subject", options=list(options.keys()))
    with col2:
        if st.button("Add Photos", type="primary", icon=":material/photo_prints:", width="stretch"):
            add_photos_dialog()
    subject_id = options[label]
    _open_session_banner(teacher_id, subject_id)
    st.divider()

    images = st.session_state.attendance_images
    if images:
        st.header("Added Photos")
        for idx, (col, img) in enumerate(zip(st.columns(4) * ((len(images) // 4) + 1), images)):
            with col:
                st.image(img, width="stretch", caption=f"Photo {idx + 1}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Clear all photos", width="stretch", type="tertiary", icon=":material/delete:", disabled=not images):
            st.session_state.attendance_images = []
            st.rerun()
    with c2:
        if st.button("Run Face Analysis", width="stretch", type="secondary", icon=":material/analytics:", disabled=not images):
            _run_face_analysis(subject_id, images)
    with c3:
        if st.button("Use Voice Attendance", type="primary", width="stretch", icon=":material/mic:"):
            voice_attendance_dialog(subject_id)


def _open_session_banner(teacher_id: int, subject_id: int) -> None:
    """Show (and let the teacher cancel) an unfinished session so duplicates are never created."""
    try:
        open_session = session_service.find_open(teacher_id, subject_id)
    except AppError as exc:
        show_error(exc)
        return
    if not open_session:
        return
    st.info(
        f"A **{open_session['method']}** attendance session (#{open_session['session_id']}) is already open for this subject. "
        "Run the analysis to finish it, or cancel it."
    )
    if st.button("Cancel open session", key=f"cancel_open_{open_session['session_id']}", type="tertiary", icon=":material/cancel:"):
        try:
            session_service.discard(teacher_id, open_session["session_id"])
        except AppError as exc:
            show_error(exc)
            return
        st.session_state.attendance_images = st.session_state.get("attendance_images", [])
        st.session_state.voice_attendance_results = None
        st.rerun()


def _run_face_analysis(subject_id: int, images: list) -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    try:
        roster = enrollment_service.subject_roster(subject_id)
        if not roster:
            st.warning("No students enrolled in this course")
            return
        session = session_service.get_or_start(teacher_id, subject_id, "FACE")
        with st.spinner("Deep scanning classroom photos..."):
            detections = recognition_service.detect_faces_in_photos(images, roster)
        rows, records = attendance_service.build_attendance_rows(roster, detections)
    except AppError as exc:
        show_error(exc)
        return
    attendance_result_dialog(pd.DataFrame(rows), records, session["session_id"])


def _share_button(subject: dict) -> None:
    if st.button(f"Share Code: {subject['name']}", key=f"share_{subject['subject_id']}", icon=":material/share:"):
        share_subject_dialog(subject["name"], subject["subject_code"])
    st.space()


def teacher_tab_manage_subjects() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects")
    with col2:
        if st.button("Create New Subject", width="stretch"):
            create_subject_dialog(teacher_id)

    subjects = _load_subjects(teacher_id)
    if subjects is None:
        return
    if not subjects:
        st.info("No subjects found. Create one above.")
        return
    for sub in subjects:  # every subject is rendered (the original rendered only the last one)
        subject_card(
            name=sub["name"],
            code=sub["subject_code"],
            section=sub["section"],
            stats=[("🫂", "Students", sub["total_students"]), ("🕰️", "Classes", sub["total_classes"])],
            footer_callback=partial(_share_button, sub),
        )
