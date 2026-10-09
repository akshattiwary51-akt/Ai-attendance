import streamlit as st

from src.services import session_service
from src.ui.feedback import show_error
from src.utils.errors import AppError


def _reset():
    st.session_state.voice_attendance_results = None
    st.session_state.attendance_images = []


def show_attendance_result(df, records, session_id):
    """Review step: nothing is saved until the teacher confirms."""
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.write("Please review attendance before confirming.")
    st.dataframe(df, hide_index=True, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Discard", width="stretch"):
            try:
                session_service.discard(teacher_id, session_id)
            except AppError as exc:
                show_error(exc)
                return
            _reset()
            st.rerun()
    with col2:
        if st.button("Confirm & Save", width="stretch", type="primary"):
            try:
                inserted = session_service.confirm(teacher_id, session_id, records)
            except AppError as exc:
                show_error(exc)
                return
            st.toast("Attendance saved" if inserted else "Attendance was already saved")
            _reset()
            st.rerun()


@st.dialog("Attendance Reports")
def attendance_result_dialog(df, records, session_id):
    show_attendance_result(df, records, session_id)
