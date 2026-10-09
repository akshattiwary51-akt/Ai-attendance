import streamlit as st

from src.services import subject_service
from src.ui.feedback import show_error
from src.utils.errors import AppError


@st.dialog("Create New Subject")
def create_subject_dialog(teacher_id):
    st.write("Enter the details of the new subject")
    code = st.text_input("Subject Code", placeholder="CS101")
    name = st.text_input("Subject Name", placeholder="Introduction to Computer Science")
    section = st.text_input("Section", placeholder="A")

    if st.button("Create Subject Now", type="primary", width="stretch"):
        try:
            subject_service.create_subject(teacher_id, code, name, section)
        except AppError as exc:
            show_error(exc)
        else:
            st.toast("Subject created successfully!")
            st.rerun()
