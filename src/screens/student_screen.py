"""Student portal (UI only - all logic lives in services)."""
from __future__ import annotations

from functools import partial

import streamlit as st

from src.components.assistant_chat import assistant_chat
from src.components.dialog_enroll import enroll_dialog
from src.components.footer import footer_dashboard
from src.components.header import header_dashboard
from src.components.subject_card import subject_card
from src.screens.teacher_analytics import RISK_TEXT
from src.services import analytics_service, auth_service, dashboard_service, enrollment_service, recognition_service
from src.ui.auth_forms import login_form
from src.ui.base_layout import style_background_dashboard, style_base_layout
from src.ui import charts
from src.ui.feedback import show_error
from src.ui.widgets import empty_state, kpi_row, progress_html, risk_badge_html, standing_message
from src.utils.html import esc
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


def _face_samples_panel() -> None:
    """Let a student add more face samples (lighting/angle) - more samples make recognition more reliable."""
    try:
        model, n = recognition_service.my_face_sample_count()
    except AppError as exc:
        show_error(exc)
        return
    with st.expander(f"Face recognition samples: {n} of 5", expanded=n == 0):
        if n == 0:
            st.warning("You have no face sample for the current recognition model, so you cannot be recognised in class. Add one below.")
        st.caption("Add photos in different lighting or angles to improve recognition. Only a numeric template is stored, not the photo.")
        shot = st.camera_input("Take a photo (only you in frame)", key="extra_face_photo") if n < 5 else None
        if shot and st.button("Save this sample", key="save_face_sample", type="primary"):
            try:
                recognition_service.add_my_face_sample(load_image(shot))
            except AppError as exc:
                show_error(exc)
                return
            st.toast("Face sample saved")
            st.rerun()


def _voice_samples_panel() -> None:
    """Optional voice samples (up to 5), quality-checked before saving."""
    try:
        _, n = recognition_service.my_voice_sample_count()
    except AppError as exc:
        show_error(exc)
        return
    with st.expander(f"Voice recognition samples: {n} of 5"):
        st.caption("Optional. Record a clear 3-5 second phrase in a quiet room. Only a numeric template is stored, not the recording. "
                   "Voice is a weaker signal than your face and can be imitated by a recording, so it is used for attendance only.")
        clip = st.audio_input("Record a short phrase", key="extra_voice_clip") if n < 5 else None
        if clip and st.button("Save voice sample", key="save_voice_sample", type="primary"):
            try:
                with st.spinner("Checking your recording.."):
                    recognition_service.add_my_voice_sample(clip.getvalue())
            except AppError as exc:
                show_error(exc)
                return
            st.toast("Voice sample saved")
            st.rerun()


def _forecast_section(student_id: int) -> None:
    """Personal trend, subject comparison and a plain-language forecast for each subject."""
    try:
        sa = analytics_service.student_analytics(student_id)
    except AppError as exc:
        show_error(exc)
        return
    st.divider()
    st.header("Trends and forecast")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Your weekly attendance")
        chart = charts.trend_line(sa.weekly)
        st.altair_chart(chart, width="stretch") if chart is not None else st.info("Your trend appears after your first recorded classes.")
    with c2:
        st.subheader("Subjects compared")
        chart = charts.comparison_bars(sa.subject_comparison)
        st.altair_chart(chart, width="stretch") if chart is not None else st.info("No classes recorded yet.")
    st.subheader("What to expect over the next month")
    st.caption("A statistical estimate from your own attendance so far, not a promise. The more classes recorded, the more reliable it is.")
    for sub, f in sa.forecasts:
        if f.risk == "NO_DATA":
            continue
        with st.expander(f"{sub['name']}: {RISK_TEXT.get(f.risk, f.risk)} · {f.prob_below_target:.0%} chance of ending below {f.target:g}%", expanded=f.risk == "HIGH"):
            st.markdown(f"Expected attendance at the end of the period: **{f.expected_pct:g}%** (likely between {f.interval_pct[0]:g}% and {f.interval_pct[1]:g}%). "
                        f"Confidence: **{f.confidence}**.")
            for reason in f.reasons:
                st.markdown(f"- {reason}")


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

    _face_samples_panel()
    _voice_samples_panel()
    try:
        with st.spinner("Loading your attendance.."):
            overview = dashboard_service.student_overview(student_id)
    except AppError as exc:
        show_error(exc)
        return

    if not overview.subjects:
        empty_state("You are not enrolled in any subject yet", "Use 'Enroll in Subject' or scan your teacher's QR code.")
        footer_dashboard()
        return

    kpi_row([
        ("Overall attendance", f"{overview.overall_percentage:g}%", f"{overview.attended} of {overview.conducted} classes"),
        ("Classes missed", overview.missed),
        ("Current streak", overview.streak, "classes in a row"),
        ("Status", {"HIGH": "High risk", "MEDIUM": "Watch", "LOW": "On track"}.get(overview.risk, "No data")),
    ])
    below = [sub["name"] for sub, standing in overview.subjects if standing.conducted and standing.percentage < standing.target]
    if below:
        st.warning("Below your attendance target in: " + ", ".join(below))

    cols = st.columns(2)
    for i, (sub, standing) in enumerate(overview.subjects):
        body = (f'<div style="margin-top:10px">{risk_badge_html(standing.risk)} <b>{standing.percentage:g}%</b> '
                f'<span class="sc-sub">(target {standing.target:g}%)</span></div>'
                f"{progress_html(standing.percentage, standing.target)}"
                f'<div class="sc-sub">{esc(standing_message(standing))}</div>')
        with cols[i % 2]:
            subject_card(
                name=sub["name"], code=sub["subject_code"], section=sub["section"],
                stats=[("📅", "Total", standing.conducted), ("✅", "Attended", standing.attended)],
                footer_callback=partial(_unenroll_button, student_id, sub), body_html=body,
            )
    _forecast_section(student_id)
    st.divider()
    st.header("Ask the attendance assistant")
    assistant_chat("STUDENT")
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
        photo2 = None
        if recognition_service.liveness_required():
            if "liveness_challenge" not in st.session_state:
                st.session_state.liveness_challenge = recognition_service.new_liveness_challenge()
            code, instruction = st.session_state.liveness_challenge
            st.info(f"Liveness check: take a second photo after you follow this instruction - **{instruction}**.")
            photo2 = st.camera_input("Second photo (liveness check)", key="liveness_photo")
        st.subheader("Optional : Voice Enrollment")
        audio = st.audio_input("Record a short phrase like 'I am present, my name is Akash.'")
        st.info(PRIVACY_NOTICE)
        consent = st.checkbox("I understand and consent to this use of my face (and voice) data")

        if st.button("Create Account", type="primary"):
            try:
                with st.spinner("Creating your account.."):
                    challenge = st.session_state.get("liveness_challenge", (None, ""))[0]
                    sample = (recognition_service.prepare_enrollment_sample(load_image(photo), load_image(photo2) if photo2 else None, challenge)
                              if photo else None)
                    voice = recognition_service.prepare_voice_sample(audio.getvalue()).embedding if audio else None
                    auth_service.register_student(email, name, password, confirm, roll, sample.embedding if sample else None, voice, consent,
                                                  face_model=sample.model_id if sample else "dlib-resnet-128",
                                                  face_quality=sample.quality if sample else None)
            except AppError as exc:
                show_error(exc)
                return
            st.session_state.pop("liveness_challenge", None)
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
