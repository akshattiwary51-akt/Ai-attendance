"""Teacher 'Reports' page: preview and download a subject's attendance as CSV or Excel."""
from __future__ import annotations

import streamlit as st

from src.services import report_service, subject_service
from src.ui.feedback import show_error
from src.ui.widgets import empty_state, page_header, section
from src.utils.errors import AppError


def teacher_tab_reports() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    page_header("Reports", "Download a subject's attendance for your records. Only completed sessions are counted.", ("Teacher", "Reports"))
    try:
        subjects = subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if not subjects:
        empty_state("No subjects yet", "Create a subject and take attendance to build a report.")
        return
    options = {f"{s['name']} ({s['subject_code']})": s["subject_id"] for s in subjects}
    label = st.selectbox("Subject", list(options), key="report_subject")
    try:
        with st.spinner("Building the report…"):
            report = report_service.subject_report(teacher_id, options[label])
    except AppError as exc:
        show_error(exc)
        return
    if not report["sessions"]:
        empty_state("No completed sessions yet", "A report appears after you confirm your first attendance session.")
        return
    code = report["subject"]["subject_code"]
    c1, c2, c3 = st.columns(3)
    c1.download_button("Student summary (CSV)", report_service.to_csv(report["students"]), file_name=f"{code}-students.csv", mime="text/csv",
                       icon=":material/download:", width="stretch", key="rep_students")
    c2.download_button("Session list (CSV)", report_service.to_csv(report["sessions"]), file_name=f"{code}-sessions.csv", mime="text/csv",
                       icon=":material/download:", width="stretch", key="rep_sessions")
    try:
        xlsx = report_service.subject_workbook(report)
    except ImportError:
        xlsx = None
    if xlsx:
        c3.download_button("Full workbook (Excel)", xlsx, file_name=f"{code}-attendance.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table_view:", width="stretch", key="rep_xlsx")
    section("Student summary")
    st.dataframe(report["students"], hide_index=True, width="stretch")
    section("Sessions")
    st.dataframe(report["sessions"], hide_index=True, width="stretch")
