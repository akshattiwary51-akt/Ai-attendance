"""Admin console: overview, approvals, user management, anomalies, audit log (UI only)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.components.footer import footer_home
from src.screens.teacher_analytics import show_anomalies
from src.services import admin_service, analytics_service
from src.ui import charts
from src.ui.auth_forms import login_form
from src.ui.feedback import show_error
from src.ui.shell import NavItem, auth_layout, sidebar
from src.ui.widgets import badge_html, empty_state, kpi_row, page_header, section, status_badge_html
from src.utils.errors import AppError
from src.utils.html import esc
from src.utils.timefmt import format_local

PAGE_KEY = "current_admin_page"
NAV = [
    NavItem("overview", "Overview", ":material/dashboard:"),
    NavItem("users", "Users", ":material/group:"),
    NavItem("anomalies", "Anomalies", ":material/flag:"),
    NavItem("audit", "Audit log", ":material/receipt_long:"),
]
_POINTS = ["Approve new teacher accounts.", "Activate or deactivate any account.", "Review the audit trail and unusual patterns across the system."]


def admin_screen() -> None:
    if "admin_data" in st.session_state:
        _dashboard()
        return
    with auth_layout("Administration", _POINTS):
        st.header("Administrator login")
        st.caption("Administrator accounts are created by the system owner, not through registration.")
        login_form("ADMIN", "admin")
    footer_home()


def _toggle(role: str, entity_id: int, active: bool) -> None:
    try:
        admin_service.set_active(role, entity_id, active)
    except AppError as exc:
        show_error(exc)
        return
    st.toast("Account approved" if active else "Account updated")
    st.rerun()


@st.dialog("Deactivate this account?")
def _confirm_deactivate(role: str, entity_id: int, name: str) -> None:
    st.write(f"**{name}** will no longer be able to log in. Their records stay in the system. You can activate the account again at any time.")
    c1, c2 = st.columns(2)
    if c1.button("Cancel", width="stretch", key=f"deact_cancel_{role}_{entity_id}"):
        st.rerun()
    if c2.button("Deactivate", width="stretch", type="primary", key=f"deact_ok_{role}_{entity_id}"):
        _toggle(role, entity_id, False)


def _user_table(role: str, rows: list[dict], id_key: str) -> None:
    if not rows:
        empty_state("Nothing here yet", "Accounts appear here after people register.")
        return
    c1, c2 = st.columns([3, 1])
    query = c1.text_input("Search by name or email", key=f"q_{role}").strip().lower()
    state = c2.selectbox("Status", ["All", "Active", "Inactive"], key=f"state_{role}")
    shown = [r for r in rows if (query in r["name"].lower() or query in r["email"].lower())
             and (state == "All" or (r["is_active"] == (state == "Active")))]
    if not shown:
        empty_state("No accounts match these filters")
        return
    st.dataframe(pd.DataFrame([{"ID": r[id_key], "Name": r["name"], "Email": r["email"], "Status": "✓ Active" if r["is_active"] else "– Inactive"} for r in shown]),
                 hide_index=True, width="stretch")
    labels = {f"{r['name']} ({r['email']})": r for r in shown}
    pick = labels[st.selectbox("Account to manage", list(labels), key=f"pick_{role}")]
    if pick["is_active"]:
        if st.button("Deactivate account", key=f"toggle_{role}", icon=":material/block:", type="secondary"):
            _confirm_deactivate(role, pick[id_key], pick["name"])
    elif st.button("Activate account", key=f"toggle_{role}", icon=":material/check_circle:", type="primary"):
        _toggle(role, pick[id_key], True)


def _overview(teachers: list[dict]) -> None:
    admin = st.session_state.admin_data
    page_header(f"Welcome, {admin['name']}", "System activity, pending approvals and totals across all subjects.", ("Admin", "Overview"))
    try:
        ov = admin_service.overview()
    except AppError as exc:
        show_error(exc)
        return
    avg = ov.get("average_attendance")
    kpi_row([("Teachers", ov["teachers"]), ("Students", ov["students"]), ("Pending approvals", ov["pending_teachers"]), ("Subjects", ov["subjects"])])
    kpi_row([("Sessions today", ov["sessions_today"]), ("Classes attended", ov["attended"]), ("Records counted", ov["conducted"]),
             ("Average attendance", f"{float(avg):g}%" if avg is not None else "—")])

    section("Teacher approvals", "New teacher accounts stay inactive until you approve them.")
    pending = [t for t in teachers if not t["is_active"]]
    if not pending:
        st.success("No teacher accounts are waiting for approval.")
    for t in pending:
        col1, col2 = st.columns([4, 1], vertical_alignment="center")
        col1.markdown(f"**{esc(t['name'])}**<br><span class='sc-sub'>{esc(t['email'])}</span> {status_badge_html('PENDING')}", unsafe_allow_html=True)
        if col2.button("Approve", key=f"approve_{t['teacher_id']}", type="primary", width="stretch"):
            _toggle("TEACHER", t["teacher_id"], True)

    section("Attendance activity", "Completed sessions per week, all subjects.")
    try:
        with st.spinner("Loading activity…"):
            activity = analytics_service.admin_activity("week")
    except AppError as exc:
        show_error(exc)
        return
    chart = charts.status_bars(activity)
    if chart is None:
        empty_state("No completed sessions yet", "Activity appears after teachers save their first attendance session.")
    else:
        st.altair_chart(chart, width="stretch")


def _dashboard() -> None:
    admin = st.session_state.admin_data
    page = sidebar(role_label="Administrator", name=admin["name"], items=NAV, state_key=PAGE_KEY, default="overview")
    try:
        teachers = admin_service.teachers()
        students = admin_service.students() if page == "users" else []
        audit = admin_service.audit_log() if page == "audit" else []
    except AppError as exc:
        show_error(exc)
        return
    if page == "users":
        page_header("Users", "Search teachers and students, and activate or deactivate accounts.", ("Admin", "Users"))
        t_teachers, t_students = st.tabs(["Teachers", "Students"])
        with t_teachers:
            _user_table("TEACHER", teachers, "teacher_id")
        with t_students:
            _user_table("STUDENT", students, "student_id")
    elif page == "anomalies":
        page_header("Anomalies", "Unusual patterns detected across the system. Flags only; nothing is changed.", ("Admin", "Anomalies"))
        try:
            with st.spinner("Checking recent sessions…"):
                show_anomalies(analytics_service.admin_anomalies(), "No unusual patterns detected across the system.")
        except AppError as exc:
            show_error(exc)
    elif page == "audit":
        page_header("Audit log", "The most recent security-relevant events, newest first.", ("Admin", "Audit log"))
        if not audit:
            empty_state("No audit entries yet", "Approvals, corrections and account changes are recorded here.")
        else:
            st.dataframe([{"When": format_local(a["created_at"]), "Actor": f"{a['actor_role']} {a['actor_id'] or ''}".strip(), "Action": a["action"],
                           "Entity": f"{a['entity_type']} {a['entity_id'] or ''}".strip()} for a in audit], hide_index=True, width="stretch")
    else:
        _overview(teachers)
