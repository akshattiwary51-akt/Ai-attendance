"""Teacher Dashboard / Students / Settings tabs and the per-subject detail (UI only)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from datetime import datetime

from src.components.subject_card import subject_card
from src.services import analytics_service, dashboard_service, invite_service, notification_service, subject_service
from src.ui import charts
from src.ui.feedback import show_error
from src.ui.notifications import notifications_panel
from src.ui.widgets import empty_state, kpi_row, page_header, plain_status, section, status_badge_html
from src.utils.errors import AppError
from src.utils.html import esc
from src.utils.timefmt import format_local, local_tz, parse_ts

_RISK_TEXT = {"HIGH": "High risk", "MEDIUM": "Watch", "LOW": "On track", "NO_DATA": "No data"}


def _risk_text(level: str) -> str:
    return _RISK_TEXT.get(level, "No data")


TAB_KEY = "current_teacher_tab"


def _safe(fn, default):
    """Notifications are a convenience: a failing lookup must never break the dashboard."""
    try:
        return fn()
    except AppError:
        return default


def _goto(tab: str, **extra) -> None:
    st.session_state.update(current_teacher_tab=tab, **extra)


def teacher_tab_dashboard() -> None:
    teacher = st.session_state.teacher_data
    teacher_id = teacher["teacher_id"]
    page_header(f"Welcome, {teacher['name']}", "Today's classes, the students who need attention, and what to do next.", ("Teacher", "Dashboard"))
    try:
        with st.spinner("Loading your dashboard…"):
            ov = dashboard_service.teacher_overview(teacher_id)
            subjects = subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if ov.total_subjects == 0:
        empty_state("No subjects yet", "Create your first subject in the Subjects tab to start taking attendance.")
        st.button("Create a subject", icon=":material/add:", type="primary", key="dash_create", on_click=_goto, args=("manage_subjects",))
        return

    open_now = [r for r in ov.recent_sessions if r["status"] == "OPEN"]
    with st.container(key="hero"):
        st.markdown('<p class="sc-hero-title">Ready to take attendance?</p>'
                    '<p class="sc-hero-body">Choose a class, add classroom photos or a voice recording, and review the results before anything is saved.</p>',
                    unsafe_allow_html=True)
        if open_now:
            st.markdown(f'<p class="sc-hero-body"><b>{len(open_now)} unfinished session{"s" if len(open_now) != 1 else ""}</b> waiting for review.</p>', unsafe_allow_html=True)
        st.button("Take attendance", icon=":material/photo_camera:", type="primary", key="hero_take", on_click=_goto, args=("take_attendance",))

    pending = _safe(lambda: len(invite_service.pending_requests()), 0)
    flags = _safe(lambda: sum(a.severity == "HIGH" for a in analytics_service.teacher_anomalies(teacher_id)), 0)
    st.space("small")
    notifications_panel(notification_service.for_teacher(ov, pending, flags), TAB_KEY)
    avg = f"{ov.average_attendance:g}%" if ov.average_attendance is not None else "—"
    kpi_row([("Subjects", ov.total_subjects), ("Students", ov.total_students), ("Sessions today", ov.sessions_today),
             ("Average attendance", avg, f"{ov.low_attendance_students} student{'s' if ov.low_attendance_students != 1 else ''} below target")])

    section("Today's sessions", "From your five most recent sessions.")
    today = datetime.now(local_tz()).date()
    todays = [r for r in ov.recent_sessions if parse_ts(r["when"]).astimezone(local_tz()).date() == today and r["status"] != "CANCELLED"]
    if not todays:
        empty_state("No sessions yet today", "Take attendance to start one.")
    else:
        for r in todays:
            c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="center")
            c1.markdown(f"**{esc(r['subject'])}**<br><span class='sc-sub'>{esc(format_local(r['when']))}, {esc(r['method'].replace('_', ' ').title())}</span>", unsafe_allow_html=True)
            c2.markdown(status_badge_html(r["status"]) + (f" &nbsp;<span class='sc-sub sc-num'>{esc(r['present'])}/{esc(r['conducted'])} present</span>" if r["status"] == "COMPLETED" else ""),
                        unsafe_allow_html=True)
            if r["status"] == "OPEN":
                c3.button("Finish", key=f"finish_{r['session_id']}", on_click=_goto, args=("take_attendance",), kwargs={"attendance_subject_id": None})

    section("Your subjects")
    cols = st.columns(2)
    for i, sub in enumerate(subjects):
        with cols[i % 2]:
            subject_card(name=sub["name"], code=sub["subject_code"], section=sub["section"],
                         stats=[("", "students", sub["total_students"]), ("", "classes", sub["total_classes"])])
            b1, b2 = st.columns(2)
            b1.button("Take attendance", key=f"dash_take_{sub['subject_id']}", icon=":material/photo_camera:", width="stretch", type="secondary",
                      on_click=_goto, args=("take_attendance",), kwargs={"attendance_subject_id": sub["subject_id"]})
            b2.button("View records", key=f"dash_records_{sub['subject_id']}", icon=":material/fact_check:", width="stretch", type="tertiary",
                      on_click=_goto, args=("attendance_records",))

    section("Students needing attention", "Based on each subject's attendance target.")
    if not ov.at_risk:
        st.success("Nobody is currently at risk.")
    else:
        st.dataframe(pd.DataFrame([{"Student": r["name"], "Subject": r["subject"], "Attendance %": r["percentage"],
                                    "Risk": _risk_text(r["risk"]), "Why": r["reason"]} for r in ov.at_risk[:10]]),
                     hide_index=True, width="stretch")
    section("Recent sessions")
    if not ov.recent_sessions:
        empty_state("No sessions yet", "Take attendance to create one.")
    else:
        st.dataframe(pd.DataFrame([{"Subject": r["subject"], "When": format_local(r["when"]), "Method": r["method"], "Status": plain_status(r["status"]),
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
            st.altair_chart(charts.trend_line([{"period": format_local(t["when"]), "percentage": t["percentage"]} for t in d["trend"]]), width="stretch")
    with t_sessions:
        if not d["sessions"]:
            st.info("No sessions yet.")
        else:
            st.dataframe(pd.DataFrame([{"When": format_local(s["started_at"]), "Method": s["method"], "Status": s["status"],
                                        "Present": s["present"] + s["late"], "Absent": s["absent"], "Excused": s["excused"]} for s in d["sessions"]]),
                         hide_index=True, width="stretch")


def teacher_tab_students() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    page_header("Students", "Everyone enrolled in your subjects, with their attendance and risk level.", ("Teacher", "Students"))
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
    page_header("Settings", "Set the minimum attendance each subject expects. Risk levels and forecasts use these targets.", ("Teacher", "Settings"))
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
