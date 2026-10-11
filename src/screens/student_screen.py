"""Student portal (UI only - all logic lives in services)."""
from __future__ import annotations

from datetime import date, timedelta
from functools import partial

import pandas as pd
import streamlit as st

from src.components.assistant_chat import assistant_chat
from src.components.dialog_enroll import enroll_dialog
from src.components.footer import footer_home
from src.components.subject_card import subject_card
from src.screens.teacher_analytics import RISK_TEXT
from src.services import analytics_service, auth_service, dashboard_service, enrollment_service, recognition_service
from src.ui import charts
from src.ui.auth_forms import login_form
from src.ui.feedback import show_error
from src.ui.shell import NavItem, auth_layout, sidebar
from src.ui.widgets import empty_state, kpi_row, note, page_header, progress_html, risk_badge_html, section, standing_message, status_text
from src.utils.errors import AppError
from src.utils.html import esc
from src.utils.images import load_image
from src.utils.timefmt import format_local, parse_ts

PAGE_KEY = "current_student_page"
NAV = [
    NavItem("overview", "Overview", ":material/dashboard:"),
    NavItem("history", "Attendance history", ":material/history:"),
    NavItem("trends", "Trends and forecast", ":material/monitoring:"),
    NavItem("samples", "Face and voice", ":material/face:"),
    NavItem("assistant", "Assistant", ":material/smart_toy:"),
]
_RISK_LABEL = {"HIGH": "High risk", "MEDIUM": "Watch", "LOW": "On track"}


def _unenroll_button(student_id: int, subject: dict) -> None:
    if st.button("Unenroll", key=f"unenroll_{subject['subject_id']}", type="tertiary", icon=":material/logout:"):
        _confirm_unenroll(student_id, subject)


@st.dialog("Unenroll from this subject?")
def _confirm_unenroll(student_id: int, subject: dict) -> None:
    st.write(f"You will stop appearing in **{subject['name']}** and your teacher will no longer be able to mark you present. "
             "Attendance already recorded stays in the teacher's records.")
    c1, c2 = st.columns(2)
    if c1.button("Keep subject", width="stretch", key=f"keep_{subject['subject_id']}"):
        st.rerun()
    if c2.button("Unenroll", width="stretch", type="primary", key=f"confirm_unenroll_{subject['subject_id']}"):
        try:
            enrollment_service.unenroll(student_id, subject["subject_id"])
        except AppError as exc:
            show_error(exc)
            return
        st.toast(f"Unenrolled from {subject['name']}")
        st.rerun()


def _face_samples_panel() -> None:
    """Let a student add more face samples (lighting/angle) - more samples make recognition more reliable."""
    try:
        model, n = recognition_service.my_face_sample_count()
    except AppError as exc:
        show_error(exc)
        return
    with st.container(border=True):
        st.subheader(f"Face samples: {n} of 5")
        if n == 0:
            st.warning("You have no face sample for the current recognition model, so you cannot be recognised in class. Add one below.")
        st.caption("Add photos in different lighting or angles to improve recognition. Only a numeric template is stored, not the photo. "
                   "If the camera does not start, allow camera access for this site in your browser settings.")
        shot = st.camera_input("Take a photo (only you in frame)", key="extra_face_photo") if n < 5 else None
        if n >= 5:
            st.success("You have the maximum number of face samples.")
        if shot and st.button("Save this sample", key="save_face_sample", type="primary"):
            try:
                with st.spinner("Checking your photo…"):
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
    with st.container(border=True):
        st.subheader(f"Voice samples: {n} of 5")
        st.caption("Optional. Record a clear 3-5 second phrase in a quiet room. Only a numeric template is stored, not the recording. "
                   "Voice is a weaker signal than your face and can be imitated by a recording, so it is used for attendance only.")
        clip = st.audio_input("Record a short phrase", key="extra_voice_clip") if n < 5 else None
        if n >= 5:
            st.success("You have the maximum number of voice samples.")
        if clip and st.button("Save voice sample", key="save_voice_sample", type="primary"):
            try:
                with st.spinner("Checking your recording…"):
                    recognition_service.add_my_voice_sample(clip.getvalue())
            except AppError as exc:
                show_error(exc)
                return
            st.toast("Voice sample saved")
            st.rerun()


def _forecast_section(student_id: int) -> None:
    """Personal trend, subject comparison and a plain-language forecast for each subject."""
    try:
        with st.spinner("Working out your trends…"):
            sa = analytics_service.student_analytics(student_id)
    except AppError as exc:
        show_error(exc)
        return
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Your weekly attendance")
        chart = charts.trend_line(sa.weekly)
        st.altair_chart(chart, width="stretch") if chart is not None else empty_state("No trend yet", "It appears after your first recorded classes.")
    with c2:
        st.subheader("Subjects compared")
        chart = charts.comparison_bars(sa.subject_comparison)
        st.altair_chart(chart, width="stretch") if chart is not None else empty_state("No classes recorded yet")
    st.subheader("What to expect over the next month")
    st.caption("A statistical estimate from your own attendance so far, not a promise. The more classes recorded, the more reliable it is.")
    shown = False
    for sub, f in sa.forecasts:
        if f.risk == "NO_DATA":
            continue
        shown = True
        with st.expander(f"{sub['name']}: {RISK_TEXT.get(f.risk, f.risk)}, {f.prob_below_target:.0%} chance of ending below {f.target:g}%", expanded=f.risk == "HIGH"):
            st.markdown(f"Expected attendance at the end of the period: **{f.expected_pct:g}%** (likely between {f.interval_pct[0]:g}% and {f.interval_pct[1]:g}%). "
                        f"Confidence: **{f.confidence}**.")
            for reason in f.reasons:
                st.markdown(f"- {reason}")
    if not shown:
        empty_state("No forecast yet", "Forecasts appear once classes have been recorded for your subjects.")


def _history_page(student_id: int) -> None:
    page_header("Attendance history", "Every class recorded for you, newest first. Only your own records are shown.", ("Student", "Attendance history"))
    try:
        with st.spinner("Loading your history…"):
            rows = dashboard_service.student_history(student_id)
    except AppError as exc:
        show_error(exc)
        return
    if not rows:
        empty_state("No classes recorded yet", "Your attendance appears here after your teacher saves a session.")
        return
    subjects = sorted({r["subject"] for r in rows})
    days = [parse_ts(r["when"]).date() for r in rows]
    c1, c2, c3 = st.columns([2, 2, 2])
    picked = c1.multiselect("Subject", subjects, placeholder="All subjects", key="hist_subjects")
    status = c2.selectbox("Status", ["All", "Present", "Late", "Absent", "Excused"], key="hist_status")
    span = c3.date_input("Date range", value=(min(days), max(days)), min_value=min(days), max_value=max(max(days), date.today()), key="hist_range")
    start, end = (span[0], span[1]) if isinstance(span, (tuple, list)) and len(span) == 2 else (min(days), max(days))
    shown = [r for r, d in zip(rows, days)
             if (not picked or r["subject"] in picked) and (status == "All" or r["status"] == status.upper()) and start <= d <= end]
    if not shown:
        empty_state("No classes match these filters", "Widen the date range or clear a filter.")
        return
    counted = [r for r in shown if r["status"] in ("PRESENT", "LATE", "ABSENT")]
    attended = sum(r["status"] in ("PRESENT", "LATE") for r in counted)
    kpi_row([("Classes shown", len(shown)), ("Attended", attended), ("Missed", len(counted) - attended)])
    st.dataframe(pd.DataFrame([{"Date": format_local(r["when"]), "Subject": r["subject"], "Status": status_text(r["status"])} for r in shown]),
                 hide_index=True, width="stretch")


def _overview_page(student: dict) -> None:
    student_id = student["student_id"]
    first = str(student["name"]).split()[0] if str(student["name"]).split() else "there"
    page_header(f"Welcome, {student['name']}", "Where your attendance stands in each subject today.", ("Student", "Overview"))
    if st.button("Enroll in a subject", type="primary", icon=":material/add:", key="enroll_btn"):
        enroll_dialog()
    try:
        _, n_faces = recognition_service.my_face_sample_count()
    except AppError:
        n_faces = None
    if n_faces == 0:
        st.warning("You have no face sample for the current recognition model, so you cannot be recognised in class. Add one in Face and voice.")
        st.button("Add a face sample", icon=":material/face:", key="nudge_face", on_click=lambda: st.session_state.__setitem__(PAGE_KEY, "samples"))
    try:
        with st.spinner("Loading your attendance…"):
            overview = dashboard_service.student_overview(student_id)
    except AppError as exc:
        show_error(exc)
        return
    if not overview.subjects:
        empty_state(f"You are not enrolled in any subject yet, {first}", "Use Enroll in a subject, or scan your teacher's QR code.")
        return

    kpi_row([
        ("Overall attendance", f"{overview.overall_percentage:g}%", f"{overview.attended} of {overview.conducted} classes"),
        ("Classes missed", overview.missed),
        ("Current streak", overview.streak, "classes in a row"),
        ("Status", _RISK_LABEL.get(overview.risk, "No data")),
    ])
    below = [sub["name"] for sub, standing in overview.subjects if standing.conducted and standing.percentage < standing.target]
    if below:
        st.warning("Below your attendance target in: " + ", ".join(below))

    section("Your subjects")
    cols = st.columns(2)
    for i, (sub, standing) in enumerate(overview.subjects):
        body = (f'<div style="margin-top:.6rem">{risk_badge_html(standing.risk)} <b class="sc-num">{standing.percentage:g}%</b> '
                f'<span class="sc-sub">target {standing.target:g}%</span></div>'
                f"{progress_html(standing.percentage, standing.target)}"
                f'<div class="sc-sub">{esc(standing_message(standing))}</div>')
        with cols[i % 2]:
            subject_card(
                name=sub["name"], code=sub["subject_code"], section=sub["section"],
                stats=[("", "classes", standing.conducted), ("", "attended", standing.attended)],
                footer_callback=partial(_unenroll_button, student_id, sub), body_html=body,
            )
    section("Recent classes", "Your latest five records.")
    try:
        recent = dashboard_service.student_history(student_id)[:5]
    except AppError as exc:
        show_error(exc)
        return
    if not recent:
        empty_state("No classes recorded yet")
    else:
        st.dataframe(pd.DataFrame([{"Date": format_local(r["when"]), "Subject": r["subject"], "Status": status_text(r["status"])} for r in recent]),
                     hide_index=True, width="stretch")
        st.button("See all history", type="tertiary", key="see_history", on_click=lambda: st.session_state.__setitem__(PAGE_KEY, "history"))


def student_dashboard() -> None:
    student = st.session_state.student_data
    page = sidebar(role_label="Student", name=student["name"], items=NAV, state_key=PAGE_KEY, default="overview")
    if page == "history":
        _history_page(student["student_id"])
    elif page == "trends":
        page_header("Trends and forecast", "How your attendance is moving and where it is likely to end up.", ("Student", "Trends"))
        _forecast_section(student["student_id"])
    elif page == "samples":
        page_header("Face and voice", "Samples SnapClass uses to recognise you in class.", ("Student", "Face and voice"))
        _face_samples_panel()
        _voice_samples_panel()
    elif page == "assistant":
        page_header("Attendance assistant", "Ask about your own attendance in plain language.", ("Student", "Assistant"))
        assistant_chat("STUDENT")
    else:
        _overview_page(student)


PRIVACY_NOTICE = (
    "**Biometric data notice.** To mark your attendance automatically, SnapClass stores a mathematical template of your face "
    "(and your voice, if you add one) - not the photo or recording itself. Templates are used only for attendance in the "
    "subjects you join, are visible only to those subjects' teachers' recognition process, and can be deleted on request."
)


def _registration_form() -> None:
    st.header("Create your student account")
    st.caption("Four short steps: your details, a face photo, an optional voice sample and your consent.")
    with st.container(border=True):
        st.subheader("Your details")
        name = st.text_input("Full name", placeholder="E.g. Hamza Rizvi", key="reg_s_name", autocomplete="name")
        email = st.text_input("Email", placeholder="you@college.edu", key="reg_s_email", autocomplete="email")
        roll = st.text_input("Roll or enrolment number (optional)", key="reg_s_roll")
        password = st.text_input("Password", type="password", help="At least 8 characters.", key="reg_s_pw", autocomplete="new-password")
        confirm = st.text_input("Confirm password", type="password", key="reg_s_pw2", autocomplete="new-password")
    with st.container(border=True):
        st.subheader("Face photo")
        st.caption("Look at the camera in good light with only you in the frame. If the camera does not start, allow camera access for this site in your browser settings.")
        photo = st.camera_input("Take a clear photo of your face", key="reg_s_photo")
        photo2 = None
        if recognition_service.liveness_required():
            if "liveness_challenge" not in st.session_state:
                st.session_state.liveness_challenge = recognition_service.new_liveness_challenge()
            code, instruction = st.session_state.liveness_challenge
            st.info(f"Liveness check: take a second photo after you follow this instruction - **{instruction}**.")
            photo2 = st.camera_input("Second photo (liveness check)", key="liveness_photo")
    with st.container(border=True):
        st.subheader("Voice sample (optional)")
        audio = st.audio_input("Record a short phrase like 'I am present, my name is Akash.'", key="reg_s_audio")
    with st.container(border=True):
        st.subheader("Consent")
        st.info(PRIVACY_NOTICE)
        consent = st.checkbox("I understand and consent to this use of my face (and voice) data", key="reg_s_consent")

    if st.button("Create account", type="primary", icon=":material/person_add:", width="stretch", key="reg_s_submit"):
        try:
            with st.spinner("Creating your account…"):
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
        st.success("Account created. Log in now. If email confirmation is enabled, confirm your email first.")
        st.session_state.student_login_type = "login"


_POINTS = ["See your attendance in every subject and whether you are on target.",
           "Get a plain-language forecast so you know how many classes you can still miss.",
           "Your face and voice are stored as numeric templates, never as photos or recordings."]


def student_screen() -> None:
    if "student_data" in st.session_state:
        student_dashboard()
        return
    registering = st.session_state.get("student_login_type", "login") == "register"
    with auth_layout("Know where your attendance stands", _POINTS):
        if registering:
            _registration_form()
            if st.button("I already have an account", type="tertiary", icon=":material/login:", width="stretch"):
                st.session_state.student_login_type = "login"
                st.rerun()
        else:
            st.header("Student login")
            st.caption("Use the email and password you registered with.")
            login_form("STUDENT", "student")
            st.divider()
            st.caption("New to SnapClass?")
            if st.button("Create a student account", type="secondary", icon=":material/person_add:", width="stretch"):
                st.session_state.student_login_type = "register"
                st.rerun()
    footer_home()
