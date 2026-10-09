import streamlit as st

from src.services import enrollment_service
from src.services.enrollment_service import EnrollOutcome
from src.ui.feedback import show_error
from src.utils.errors import AppError


@st.dialog("Enroll in Subject")
def enroll_dialog():
    st.write("Enter the subject code provided by your teacher to enroll")
    join_code = st.text_input("Subject Code", placeholder="Eg. CS101")

    if st.button("Enroll now", type="primary", width="stretch"):
        try:
            outcome, _ = enrollment_service.enroll_by_code(join_code)
        except AppError as exc:
            show_error(exc)
            return
        if outcome is EnrollOutcome.NOT_FOUND:
            st.error("Subject code not found.")
        elif outcome is EnrollOutcome.ALREADY_ENROLLED:
            st.warning("You are already enrolled in this subject.")
        else:
            st.success("Successfully enrolled!")
            st.rerun()
