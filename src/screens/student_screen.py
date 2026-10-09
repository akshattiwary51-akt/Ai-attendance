"""Student portal (UI only - all logic lives in services)."""
from __future__ import annotations

from functools import partial

import streamlit as st

from src.components.dialog_enroll import enroll_dialog
from src.components.footer import footer_dashboard
from src.components.header import header_dashboard
from src.components.subject_card import subject_card
from src.services import attendance_service, auth_service, enrollment_service, recognition_service
from src.pipelines.voice_pipeline import get_voice_embedding
from src.ui.auth_forms import login_form
from src.ui.base_layout import style_background_dashboard, style_base_layout
from src.ui.feedback import show_error
from src.utils.errors import AppError
from src.utils.images import load_image
from src.utils.session import logout


def _unenroll_button(student_id: int, subject: dict) -> None:
    if st.button("Unenroll from this course", key=f"unenroll_{subject['subject_id']}", type="tertiary", width="stretch", icon=":material/delete_forever:"):
        try:
            enrollment_service.unenroll(student_id, subject["subject_id"])
        except AppError as exc:
            show_error(exc)
            return
        st.toast(f"Unenrolled from {subject['name']} successfully!")
        st.rerun()


def student_dashboard() -> None:
    student = st.session_state.student_data
    student_id = student["student_id"]
    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"Welcome, {student['name']}")
        if st.button("Logout", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            logout()
            st.rerun()

    st.space()
    c1, c2 = st.columns(2)
    with c1:
        st.header("Your Enrolled Subjects")
    with c2:
        if st.button("Enroll in Subject", type="primary", width="stretch"):
            enroll_dialog()
    st.divider()

    try:
        with st.spinner("Loading your enrolled subjects.."):
            subjects = enrollment_service.student_subjects(student_id)
            stats_map = attendance_service.get_student_stats(student_id)
    except AppError as exc:
        show_error(exc)
        return

    if not subjects:
        st.info("You are not enrolled in any subject yet. Use 'Enroll in Subject' or scan your teacher's QR code.")
    cols = st.columns(2)
    for i, sub in enumerate(subjects):
        stats = stats_map.get(sub["subject_id"], {"total": 0, "attended": 0, "percentage": 0.0})
        with cols[i % 2]:
            subject_card(
                name=sub["name"],
                code=sub["subject_code"],
                section=sub["section"],
                stats=[("📅", "Total", stats["total"]), ("✅", "Attended", stats["attended"]), ("📊", "% Attendance", stats["percentage"])],
                footer_callback=partial(_unenroll_button, student_id, sub),
            )
    footer_dashboard()


PRIVACY_NOTICE = (
    "**Biometric data notice.** To mark your attendance automatically, SnapClass stores a mathematical template of your face "
    "(and your voice, if you add one) - not the photo or recording itself. Templates are used only for attendance in the "
    "subjects you join, are visible only to those subjects' teachers' recognition process, and can be deleted on request."
)


def _registration_form() -> None:
    with st.container(border=True):
        st.header("Create your student account")
        name = st.text_input("Full name", placeholder="E.g. Hamza Rizvi")
        email = st.text_input("Email", placeholder="you@college.edu")
        roll = st.text_input("Roll / enrolment number (optional)")
        password = st.text_input("Password (min 8 characters)", type="password")
        confirm = st.text_input("Confirm password", type="password")
        photo = st.camera_input("Take a clear photo of your face (look at the camera, good light)")
        st.subheader("Optional : Voice Enrollment")
        audio = st.audio_input("Record a short phrase like 'I am present, my name is Akash.'")
        st.info(PRIVACY_NOTICE)
        consent = st.checkbox("I understand and consent to this use of my face (and voice) data")

        if st.button("Create Account", type="primary"):
            try:
                with st.spinner("Creating your account.."):
                    face = recognition_service.extract_single_face_embedding(load_image(photo)) if photo else None
                    if photo and face is None:
                        st.error("We need exactly one clear face in the photo.")
                        return
                    voice = get_voice_embedding(audio.getvalue()) if audio else None
                    auth_service.register_student(email, name, password, confirm, roll, face, voice, consent)
            except AppError as exc:
                show_error(exc)
                return
            st.success("Account created! Log in now. (If email confirmation is enabled, confirm your email first.)")
            st.session_state.student_login_type = "login"


def student_screen() -> None:
    style_background_dashboard()
    style_base_layout()

    if "student_data" in st.session_state:
        student_dashboard()
        return

    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go back to Home", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            st.session_state["login_type"] = None
            st.rerun()

    if st.session_state.get("student_login_type", "login") == "register":
        _registration_form()
        if st.button("Already registered? Login", type="tertiary"):
            st.session_state.student_login_type = "login"
            st.rerun()
    else:
        st.header("Student login", text_alignment="center")
        st.space()
        login_form("STUDENT", "student")
        st.divider()
        if st.button("New student? Create an account", type="primary", width="stretch"):
            st.session_state.student_login_type = "register"
            st.rerun()
    footer_dashboard()
