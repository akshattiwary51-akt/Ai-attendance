"""Teacher Dashboard / Students / Settings tabs and the per-subject detail (UI only)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.services import dashboard_service, subject_service
from src.ui.feedback import show_error
from src.ui.widgets import empty_state, kpi_row, risk_badge_html
from src.utils.errors import AppError
from src.utils.timefmt import format_local

_RISK_TEXT = {"HIGH": "High risk", "MEDIUM": "Watch", "LOW": "On track", "NO_DATA": "No data"}


def _risk_text(level: str) -> str:
    return _RISK_TEXT.get(level, "No data")


def teacher_tab_dashboard() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Dashboard")
    try:
        ov = dashboard_service.teacher_overview(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if ov.total_subjects == 0:
        empty_state("No subjects yet", "Create your first subject in the Subjects tab to start taking attendance.")
        return
    avg = f"{ov.average_attendance:g}%" if ov.average_attendance is not None else "—"
    kpi_row([("Subjects", ov.total_subjects), ("Students", ov.total_students), ("Sessions today", ov.sessions_today)])
    kpi_row([("Average attendance", avg), ("Low-attendance students", ov.low_attendance_students)])

    st.subheader("Students needing attention")
    if not ov.at_risk:
        st.success("Nobody is currently at risk.")
    else:
        st.dataframe(pd.DataFrame([{"Student": r["name"], "Subject": r["subject"], "Attendance %": r["percentage"],
                                    "Risk": _risk_text(r["risk"]), "Why": r["reason"]} for r in ov.at_risk[:10]]),
                     hide_index=True, width="stretch")
    st.subheader("Recent sessions")
    if not ov.recent_sessions:
        empty_state("No sessions yet", "Take attendance to create one.")
    else:
        st.dataframe(pd.DataFrame([{"Subject": r["subject"], "When": format_local(r["when"]), "Method": r["method"], "Status": r["status"],
                                    "Present": f"{r['present']}/{r['conducted']}"} for r in ov.recent_sessions]), hide_index=True, width="stretch")


def subject_detail_view(subject_id: int) -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    try:
        d = dashboard_service.subject_detail(teacher_id, subject_id)
    except AppError as exc:
        show_error(exc)
        return
    t_students, t_trend, t_sessions = st.tabs(["Students", "Trend", "Sessions"])
    with t_students:
        if not d["students"]:
            empty_state("No students enrolled", "Share the subject code or QR so students can join.")
        else:
            st.dataframe(pd.DataFrame([{"Student": s["name"], "Attended": s["standing"].attended, "Classes": s["standing"].conducted,
                                        "Attendance %": s["standing"].percentage, "Risk": _risk_text(s["standing"].risk)} for s in d["students"]]),
                         hide_index=True, width="stretch")
    with t_trend:
        if len(d["trend"]) < 2:
            st.info("The trend appears after two completed sessions.")
        else:
            st.line_chart(pd.DataFrame({"Attendance %": [t["percentage"] for t in d["trend"]]}, index=[format_local(t["when"]) for t in d["trend"]]))
    with t_sessions:
        if not d["sessions"]:
            st.info("No sessions yet.")
        else:
            st.dataframe(pd.DataFrame([{"When": format_local(s["started_at"]), "Method": s["method"], "Status": s["status"],
                                        "Present": s["present"] + s["late"], "Absent": s["absent"], "Excused": s["excused"]} for s in d["sessions"]]),
                         hide_index=True, width="stretch")


def teacher_tab_students() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Students")
    try:
        people = dashboard_service.students_overview(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if not people:
        empty_state("No students yet", "Students appear here after they enrol in one of your subjects.")
        return
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("Search by name", key="student_search").strip().lower()
    risk = c2.selectbox("Risk", ["All", "High risk", "Watch", "On track", "No data"], key="student_risk")
    rows = [p for p in people if query in p["name"].lower() and (risk == "All" or _risk_text(p["risk"]) == risk)]
    if not rows:
        empty_state("No students match these filters")
        return
    st.dataframe(pd.DataFrame([{"Student": p["name"], "Subjects": len(p["subjects"]), "Attendance %": p["percentage"], "Risk": _risk_text(p["risk"])}
                               for p in rows]), hide_index=True, width="stretch")
    pick = st.selectbox("Student detail", [p["name"] + f" (#{p['student_id']})" for p in rows], key="student_pick")
    chosen = next(p for p in rows if pick == p["name"] + f" (#{p['student_id']})")
    st.dataframe(pd.DataFrame([{"Subject": name, "Attended": s.attended, "Classes": s.conducted, "Attendance %": s.percentage,
                                "Target %": s.target, "Risk": _risk_text(s.risk)} for name, s in chosen["subjects"]]), hide_index=True, width="stretch")


def teacher_tab_settings() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Settings")
    st.subheader("Attendance targets")
    try:
        subjects = subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if not subjects:
        empty_state("No subjects yet")
        return
    for sub in subjects:
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        value = c1.number_input(f"{sub['name']} ({sub['subject_code']}) minimum attendance %", 1.0, 100.0, float(sub["target_percent"]),
                                step=1.0, key=f"target_{sub['subject_id']}")
        if c2.button("Save", key=f"save_target_{sub['subject_id']}", type="primary"):
            try:
                subject_service.set_target(sub["subject_id"], value)
            except AppError as exc:
                show_error(exc)
                return
            st.toast("Target saved")
            st.rerun()
