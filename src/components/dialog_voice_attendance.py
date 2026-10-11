import pandas as pd
import streamlit as st

from src.components.dialog_attendance_results import start_review
from src.services import attendance_service, enrollment_service, recognition_service, session_service
from src.ui.feedback import show_error
from src.utils.errors import AppError


@st.dialog("Voice Attendance")
def voice_attendance_dialog(selected_subject_id):
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.write("Record audio of students saying 'I am present'. The AI will then recognize the students.")
    audio_data = st.audio_input("Record classroom audio")

    if st.button("Analyze Audio", width="stretch", type="primary"):
        if audio_data is None:
            st.warning("Please record audio first.")
        else:
            try:
                with st.spinner("Processing audio data"):
                    roster = enrollment_service.subject_roster(selected_subject_id)
                    if not roster:
                        st.warning("No students enrolled in this course")
                        return
                    session = session_service.get_or_start(teacher_id, selected_subject_id, "VOICE")
                    analysis = recognition_service.analyze_voice(audio_data.getvalue(), roster)
                    if analysis.with_voice == 0:
                        session_service.discard(teacher_id, session["session_id"])
                        st.error("No enrolled students have voice profiles registered")
                        return
                    rows, records = attendance_service.build_attendance_rows(roster, analysis.detections)
                    session_service.record_recognition_stats(teacher_id, session["session_id"], recognition_service.voice_stats(analysis))
                    start_review(pd.DataFrame(rows), records, session["session_id"], selected_subject_id, "VOICE", analysis.notes())
            except AppError as exc:
                show_error(exc)
            else:
                if st.session_state.get("attendance_review"):
                    st.rerun()
