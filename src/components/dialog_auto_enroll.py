import streamlit as st

from src.services import enrollment_service
from src.services.enrollment_service import EnrollOutcome
from src.ui.feedback import show_error
from src.utils.errors import AppError


def _close():
    st.query_params.clear()
    st.rerun()


@st.dialog("Quick Enrollment")
def auto_enroll_dialog(subject_code):
    try:
        subject = enrollment_service.preview_subject(subject_code)
        if subject is None:
            st.error("Subject code not found!")
            if st.button("Close"):
                _close()
            return
        if subject["enrolled"]:
            st.info("You're already enrolled!")
            if st.button("Got it!"):
                _close()
            return
        st.markdown("Would you like to enroll in **" + subject["name"].replace("*", "\\*") + "**?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("No thanks"):
                _close()
        with col2:
            if st.button("Yes enroll now!", type="primary", width="stretch"):
                outcome, _ = enrollment_service.enroll_by_code(subject_code)
                if outcome is EnrollOutcome.ENROLLED:
                    st.toast("Joined successfully!")
                _close()
    except AppError as exc:
        show_error(exc)
