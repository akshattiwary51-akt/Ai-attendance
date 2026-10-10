import pandas as pd
import streamlit as st

from src.components.dialog_attendance_results import show_attendance_result
from src.services import enrollment_service, fusion_service, recognition_service, session_service
from src.ui.feedback import show_error
from src.utils.errors import AppError


@st.dialog("Face + Voice Attendance")
def combined_attendance_dialog(subject_id: int, images: list):
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.write(f"Uses the {len(images)} classroom photo(s) you added plus a voice recording. A student seen AND heard is the strongest "
             "evidence; a student matched by only one is flagged when the evidence is weak.")
    audio = st.audio_input("Record classroom audio (students say 'I am present')")
    if st.button("Analyze face + voice", width="stretch", type="primary"):
        if not images or audio is None:
            st.warning("Add photos and record audio first.")
        else:
            try:
                with st.spinner("Analysing photos and audio.."):
                    roster = enrollment_service.subject_roster(subject_id)
                    if not roster:
                        st.warning("No students enrolled in this course")
                        return
                    session = session_service.get_or_start(teacher_id, subject_id, "FACE_PLUS_VOICE")
                    face = recognition_service.analyze_photos(images, roster)
                    voice = recognition_service.analyze_voice(audio.getvalue(), roster)
                    result = fusion_service.fuse(roster, face, voice)
                    session_service.record_recognition_stats(teacher_id, session["session_id"], recognition_service.face_stats(face))
                    rows, records = fusion_service.rows_and_records(roster, result)
                    st.session_state.combined_attendance_results = (pd.DataFrame(rows), records, session["session_id"], result.notes)
            except AppError as exc:
                show_error(exc)
    pending = st.session_state.get("combined_attendance_results")
    if pending:
        try:
            owned = session_service.get_owned_session(teacher_id, pending[2])
        except AppError:
            owned = None
        if owned and owned["subject_id"] == subject_id and owned["status"] == "OPEN":
            st.divider()
            show_attendance_result(*pending)
