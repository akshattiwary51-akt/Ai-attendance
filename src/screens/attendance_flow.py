"""Guided attendance workflow: subject -> capture -> analyze -> review -> save (UI only; services do all the work)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.components.dialog_add_photo import add_photos_dialog
from src.components.dialog_attendance_results import FLASH_KEY, current_review, reset_attendance_state, review_panel, start_review
from src.components.dialog_combined_attendance import combined_attendance_dialog
from src.components.dialog_voice_attendance import voice_attendance_dialog
from src.services import attendance_service, enrollment_service, recognition_service, session_service, subject_service
from src.ui.feedback import show_error
from src.ui.widgets import empty_state, note, page_header, section, stepper
from src.utils.errors import AppError

STEPS = ["Subject", "Capture", "Analyze", "Review", "Save"]
SUBJECT_KEY = "attendance_subject_id"


def _load_subjects(teacher_id: int) -> list[dict] | None:
    try:
        return subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return None


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
        reset_attendance_state()
        st.rerun()


def _run_face_analysis(subject_id: int, images: list) -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    try:
        roster = enrollment_service.subject_roster(subject_id)
        if not roster:
            st.warning("No students are enrolled in this subject yet. Share the subject code so students can join.")
            return
        session = session_service.get_or_start(teacher_id, subject_id, "FACE")
        with st.spinner("Scanning the classroom photos…"):
            analysis = recognition_service.analyze_photos(images, roster)
        rows, records = attendance_service.build_attendance_rows(roster, analysis.detections)
        session_service.record_recognition_stats(teacher_id, session["session_id"], recognition_service.face_stats(analysis))
    except AppError as exc:
        show_error(exc)
        return
    start_review(pd.DataFrame(rows), records, session["session_id"], subject_id, "FACE", analysis.notes())
    st.rerun()


def _saved_panel(flash: dict) -> None:
    with st.container(border=True):
        st.success(f"Attendance saved: {flash['present']} present or late, {flash['absent']} absent."
                   if flash["inserted"] else "This attendance was already saved. Nothing changed.")
        c1, c2 = st.columns(2)
        c1.button("Review or correct this session", icon=":material/fact_check:", key="flash_records", width="stretch",
                  on_click=lambda: st.session_state.update(current_teacher_tab="attendance_records", records_open_session=flash["session_id"]))
        c2.button("Take attendance for another class", icon=":material/add:", key="flash_again", width="stretch", type="primary")


def teacher_tab_take_attendance() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    page_header("Take attendance", "Pick a class, add photos or a voice recording, then review the results before saving.", ("Teacher", "Take attendance"))
    st.session_state.setdefault("attendance_images", [])

    subjects = _load_subjects(teacher_id)
    if subjects is None:
        return
    if not subjects:
        st.warning("You haven't created any subjects yet! Please create one to begin!")
        st.button("Create a subject", icon=":material/add:", key="goto_subjects", type="primary",
                  on_click=lambda: st.session_state.update(current_teacher_tab="manage_subjects"))
        return

    flash = st.session_state.pop(FLASH_KEY, None)
    review = current_review()
    options = {f"{s['name']} ({s['subject_code']})": s["subject_id"] for s in subjects}
    ids = list(options.values())
    wanted = review["subject_id"] if review else st.session_state.get(SUBJECT_KEY)
    index = ids.index(wanted) if wanted in ids else 0

    if flash:
        stepper(STEPS, len(STEPS) + 1)
        _saved_panel(flash)
        st.divider()
    else:
        stepper(STEPS, 4 if review else 3 if st.session_state.attendance_images else 2)

    with st.container(border=True):
        st.subheader("1. Choose the class")
        label = st.selectbox("Subject", options=list(options), index=index, disabled=bool(review))
    subject_id = options[label]
    st.session_state[SUBJECT_KEY] = subject_id

    if review:
        review_panel(review)
        return
    _open_session_banner(teacher_id, subject_id)

    images = st.session_state.attendance_images
    with st.container(border=True):
        st.subheader("2. Capture the class")
        st.caption("Add one or more classroom photos, a voice recording, or both. Better light and a clear view of every face give better results.")
        if images:
            for idx, (col, img) in enumerate(zip(st.columns(4) * ((len(images) // 4) + 1), images)):
                with col:
                    st.image(img, width="stretch", caption=f"Photo {idx + 1}")
        else:
            empty_state("No photos added yet", "Use Add photos to take a snapshot with the camera or upload images. A voice-only session needs no photos.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Add photos", type="secondary", icon=":material/add_a_photo:", width="stretch", key="add_photos"):
                add_photos_dialog()
        with c2:
            if st.button("Remove all photos", type="tertiary", icon=":material/delete:", width="stretch", disabled=not images, key="clear_photos"):
                st.session_state.attendance_images = []
                st.rerun()

    with st.container(border=True):
        st.subheader("3. Analyze")
        st.caption("A session opens when you analyze. It is only saved after you confirm the review, and you can discard it.")
        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("Analyze photos", width="stretch", type="primary", icon=":material/analytics:", disabled=not images, key="run_face"):
                _run_face_analysis(subject_id, images)
        with a2:
            if st.button("Use voice", width="stretch", icon=":material/mic:", key="run_voice"):
                voice_attendance_dialog(subject_id)
        with a3:
            if st.button("Face + voice", width="stretch", icon=":material/merge:", disabled=not images, key="run_combined",
                         help="Use the photos above together with a voice recording for stronger evidence."):
                combined_attendance_dialog(subject_id, images)
        note("If the camera or microphone does not start, allow access for this site in your browser settings, or upload photos instead.")
