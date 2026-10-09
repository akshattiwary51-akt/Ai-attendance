"""Minimal admin console (approvals, user activation, audit trail). Richer dashboards arrive in Phase 4."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.components.footer import footer_dashboard
from src.components.header import header_dashboard
from src.services import admin_service
from src.ui.auth_forms import login_form
from src.ui.base_layout import style_background_dashboard, style_base_layout
from src.ui.feedback import show_error
from src.utils.errors import AppError
from src.utils.session import logout
from src.utils.timefmt import format_local


def admin_screen() -> None:
    style_background_dashboard()
    style_base_layout()
    if "admin_data" in st.session_state:
        _dashboard()
        return
    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go back to Home", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            st.session_state["login_type"] = None
            st.rerun()
    st.header("Administrator login", text_alignment="center")
    st.space()
    login_form("ADMIN", "admin")
    footer_dashboard()


def _toggle(role: str, entity_id: int, active: bool) -> None:
    try:
        admin_service.set_active(role, entity_id, active)
    except AppError as exc:
        show_error(exc)
        return
    st.toast("Updated")
    st.rerun()


def _user_table(role: str, rows: list[dict], id_key: str) -> None:
    if not rows:
        st.info("Nothing here yet.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    labels = {f"#{r[id_key]} · {r['name']} · {r['email']} · {'active' if r['is_active'] else 'inactive'}": r for r in rows}
    pick = labels[st.selectbox("Select a user", list(labels), key=f"pick_{role}")]
    label, target = ("Deactivate", False) if pick["is_active"] else ("Activate", True)
    if st.button(label, key=f"toggle_{role}", type="primary" if target else "secondary"):
        _toggle(role, pick[id_key], target)


def _dashboard() -> None:
    admin = st.session_state.admin_data
    c1, c2 = st.columns(2, vertical_alignment="center", gap="large")
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"Welcome, {admin['name']}")
        if st.button("Logout", type="secondary", key="loginbackbtn", shortcut="control+backspace"):
            logout()
            st.rerun()
    st.divider()
    try:
        teachers, students, audit = admin_service.teachers(), admin_service.students(), admin_service.audit_log()
    except AppError as exc:
        show_error(exc)
        return
    pending = [t for t in teachers if not t["is_active"]]
    k1, k2, k3 = st.columns(3)
    k1.metric("Teachers", len(teachers)); k2.metric("Students", len(students)); k3.metric("Pending approvals", len(pending))

    t_pending, t_teachers, t_students, t_audit = st.tabs(["Pending approvals", "Teachers", "Students", "Audit log"])
    with t_pending:
        if not pending:
            st.success("No teacher accounts are waiting for approval.")
        for t in pending:
            col1, col2 = st.columns([3, 1], vertical_alignment="center")
            col1.markdown(f"**{t['name']}** · {t['email']}")
            if col2.button("Approve", key=f"approve_{t['teacher_id']}", type="primary"):
                _toggle("TEACHER", t["teacher_id"], True)
    with t_teachers:
        _user_table("TEACHER", teachers, "teacher_id")
    with t_students:
        _user_table("STUDENT", students, "student_id")
    with t_audit:
        if not audit:
            st.info("No audit entries yet.")
        else:
            st.dataframe([{"When": format_local(a["created_at"]), "Actor": f"{a['actor_role']} {a['actor_id'] or ''}".strip(), "Action": a["action"],
                           "Entity": f"{a['entity_type']} {a['entity_id'] or ''}".strip()} for a in audit], hide_index=True, width="stretch")
    footer_dashboard()
