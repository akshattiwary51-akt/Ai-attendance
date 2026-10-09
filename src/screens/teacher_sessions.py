"""Teacher 'Attendance Records' tab: review sessions, correct records (audited), undo, reopen."""
from __future__ import annotations

import streamlit as st

from src.services import session_service
from src.services.attendance_service import CORRECTABLE, STATUS_LABEL
from src.ui.feedback import show_error
from src.utils.errors import AppError
from src.utils.timefmt import format_local


def _act(fn, *args, success: str) -> None:
    try:
        fn(*args)
    except AppError as exc:
        show_error(exc)
        return
    st.toast(success)
    st.rerun()


def teacher_tab_attendance_records() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Attendance Records")
    try:
        sessions = session_service.list_sessions(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if sessions.empty:
        st.info("No attendance sessions yet. Take attendance to create one.")
        return

    st.dataframe(sessions, width="stretch", hide_index=True)
    st.divider()
    labels = {f"#{r.ID} · {r.Subject} · {r.Time} · {r.Status}": int(r.ID) for r in sessions.itertuples()}
    session_id = labels[st.selectbox("Open a session to review or correct", list(labels))]
    try:
        detail = session_service.session_detail(teacher_id, session_id)
    except AppError as exc:
        show_error(exc)
        return
    _render_detail(teacher_id, session_id, detail)


def _render_detail(teacher_id: int, session_id: int, detail: dict) -> None:
    session, records = detail["session"], detail["records"]
    st.subheader(f"{session['subjects']['name']} — {format_local(session['started_at'])}")
    st.caption(f"Method: {session['method']} · Status: {session['status']}")

    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if session["status"] == "COMPLETED" and st.button("Reopen session", icon=":material/lock_open:", key=f"reopen_{session_id}"):
            _act(session_service.reopen, teacher_id, session_id, success="Session reopened")
    with b2:
        if session["status"] == "OPEN" and st.button("Cancel session", icon=":material/cancel:", key=f"cancel_{session_id}"):
            _act(session_service.discard, teacher_id, session_id, success="Session cancelled")

    if not records:
        st.info("No attendance has been recorded for this session." if session["status"] != "OPEN" else "This session is still open and has no saved records.")
        return
    st.dataframe(session_service.records_table(records), width="stretch", hide_index=True)

    if session["status"] == "CANCELLED":
        return
    st.markdown("#### Correct a record")
    with st.form(f"correct_{session_id}", clear_on_submit=True):
        names = {f"{r['students']['name']} (#{r['student_id']})": r["student_id"] for r in records}
        who = st.selectbox("Student", list(names))
        new_status = st.selectbox("New status", CORRECTABLE, format_func=lambda s: STATUS_LABEL[s])
        reason = st.text_input("Reason (required, kept in the audit trail)")
        if st.form_submit_button("Apply correction", type="primary"):
            try:
                session_service.correct_record(teacher_id, session_id, names[who], new_status, reason)
            except AppError as exc:
                show_error(exc)
            else:
                st.toast("Correction saved")
                st.rerun()

    _render_corrections(teacher_id, detail["corrections"], session_id)


def _render_corrections(teacher_id: int, corrections: list[dict], session_id: int) -> None:
    if not corrections:
        return
    st.markdown("#### Correction history")
    st.dataframe(
        [{"#": c["correction_id"], "Student": c["attendance_records"]["students"]["name"], "From": c["old_status"], "To": c["new_status"],
          "Reason": c["reason"], "When": format_local(c["created_at"]), "Undone": "↩️" if c["reverted_at"] else ""} for c in corrections],
        width="stretch", hide_index=True,
    )
    undoable = session_service.undoable_corrections(corrections)
    if undoable:
        options = {f"#{c['correction_id']} · {c['attendance_records']['students']['name']}: {c['old_status']} → {c['new_status']}": c["correction_id"] for c in undoable}
        pick = st.selectbox("Undo a correction", list(options), key=f"undo_pick_{session_id}")
        if st.button("Undo selected correction", icon=":material/undo:", key=f"undo_{session_id}"):
            _act(session_service.undo_correction, teacher_id, options[pick], success="Correction undone")
