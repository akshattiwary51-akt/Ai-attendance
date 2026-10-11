"""Teacher 'Sessions and records' page: find sessions, review them, correct records (audited), undo, reopen."""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd
import streamlit as st

from src.services import session_service
from src.services.attendance_service import CORRECTABLE, STATUS_LABEL
from src.ui.dialogs import confirm_dialog
from src.ui.feedback import show_error
from src.ui.widgets import confidence_config, empty_state, page_header, plain_status, section, status_badge_html, status_text, summary_chips
from src.utils.errors import AppError
from src.utils.html import esc
from src.utils.timefmt import format_local

OPEN_KEY = "records_open_session"


def _act(fn, *args, success: str) -> None:
    try:
        fn(*args)
    except AppError as exc:
        show_error(exc)
        return
    st.toast(success)
    st.rerun()


def _filter_sessions(sessions: pd.DataFrame) -> pd.DataFrame:
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    query = c1.text_input("Search by subject or code", key="rec_query", placeholder="Type a subject name or code").strip().lower()
    subject = c2.selectbox("Subject", ["All"] + sorted(sessions["Subject"].unique()), key="rec_subject")
    status = c3.selectbox("Status", ["All", "COMPLETED", "OPEN", "CANCELLED"], format_func=lambda s: s.title(), key="rec_status")
    dates = sessions["Time"].str[:10]
    span = c4.date_input("Date range", value=(), key="rec_dates", help="Leave empty to show all dates.")
    out = sessions
    if query:
        out = out[out["Subject"].str.lower().str.contains(query, regex=False) | out["Subject Code"].str.lower().str.contains(query, regex=False)]
    if subject != "All":
        out = out[out["Subject"] == subject]
    if status != "All":
        out = out[out["Status"] == status]
    if isinstance(span, (tuple, list)) and len(span) == 2:
        out = out[(dates.loc[out.index] >= span[0].isoformat()) & (dates.loc[out.index] <= span[1].isoformat())]
    return out


def teacher_tab_attendance_records() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    page_header("Sessions and records", "Review every attendance session. Corrections need a reason and are kept in the audit trail.", ("Teacher", "Sessions and records"))
    try:
        with st.spinner("Loading sessions…"):
            sessions = session_service.list_sessions(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if sessions.empty:
        st.info("No attendance sessions yet. Take attendance to create one.")
        return

    shown = _filter_sessions(sessions)
    if shown.empty:
        empty_state("No sessions match these filters", "Clear a filter or widen the date range.")
        return
    counts = Counter(shown["Status"])
    st.markdown(summary_chips([("completed", counts.get("COMPLETED", 0), "sc-ok"), ("open", counts.get("OPEN", 0), "sc-warn"),
                               ("cancelled", counts.get("CANCELLED", 0), "sc-muted")]), unsafe_allow_html=True)
    st.dataframe(shown.assign(Status=[plain_status(s) for s in shown["Status"]], Attendance=[re.sub(r"^[^\w]+", "", a) for a in shown["Attendance"]]), width="stretch", hide_index=True)

    labels = {f"#{r.ID}, {r.Subject}, {r.Time}, {plain_status(r.Status)}": int(r.ID) for r in shown.itertuples()}
    wanted = st.session_state.pop(OPEN_KEY, None)
    index = list(labels.values()).index(wanted) if wanted in labels.values() else 0
    section("Session detail")
    session_id = labels[st.selectbox("Open a session to review or correct", list(labels), index=index)]
    try:
        detail = session_service.session_detail(teacher_id, session_id)
    except AppError as exc:
        show_error(exc)
        return
    _render_detail(teacher_id, session_id, detail)


def _render_detail(teacher_id: int, session_id: int, detail: dict) -> None:
    session, records = detail["session"], detail["records"]
    st.markdown(f"<h3 style='margin-bottom:.25rem'>{esc(session['subjects']['name'])}</h3>"
                f"<div class='sc-sub'>{esc(format_local(session['started_at']))}, method {esc(str(session['method']).replace('_', ' ').title())} &nbsp;"
                f"{status_badge_html(session['status'])}</div>", unsafe_allow_html=True)

    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if session["status"] == "COMPLETED" and st.button("Reopen session", icon=":material/lock_open:", key=f"reopen_{session_id}"):
            confirm_dialog("Reopen this session?",
                           "Reopening makes the saved attendance editable again and takes it out of every total until you save it again. The reopening is recorded in the audit log.",
                           "Reopen session", lambda: session_service.reopen(teacher_id, session_id), key=f"reopen_{session_id}_dlg", success="Session reopened")
    with b2:
        if session["status"] == "OPEN" and st.button("Cancel session", icon=":material/cancel:", key=f"cancel_{session_id}"):
            confirm_dialog("Cancel this session?", "No attendance will be saved for it. This cannot be undone, but you can take attendance again.",
                           "Cancel session", lambda: session_service.discard(teacher_id, session_id), key=f"cancel_{session_id}_dlg", success="Session cancelled",
                           cancel_label="Keep session")

    if not records:
        st.info("No attendance has been recorded for this session." if session["status"] != "OPEN" else "This session is still open and has no saved records.")
        return
    tally = Counter(r["status"] for r in records)
    st.markdown(summary_chips([("present", tally.get("PRESENT", 0), "sc-ok"), ("late", tally.get("LATE", 0), "sc-warn"), ("absent", tally.get("ABSENT", 0), "sc-bad"),
                               ("excused", tally.get("EXCUSED", 0), "sc-info")]), unsafe_allow_html=True)
    who_filter = st.text_input("Find a student in this session", key=f"rec_who_{session_id}", placeholder="Type a name").strip().lower()
    table = session_service.records_table(records)
    table = table[table["Name"].str.lower().str.contains(who_filter, regex=False)] if who_filter else table
    table = table.assign(Status=[status_text(plain_status(s).upper()) for s in table["Status"]], Corrected=["Corrected" if c else "" for c in table["Corrected"]])
    st.dataframe(table, width="stretch", hide_index=True, column_config=confidence_config())

    if session["status"] == "CANCELLED":
        return
    section("Correct a record", "Pick a student and the right status. A reason is required and is kept in the audit trail.")
    with st.form(f"correct_{session_id}", clear_on_submit=True):
        names = {f"{r['students']['name']} (#{r['student_id']})": r["student_id"] for r in records}
        who = st.selectbox("Student", list(names))
        new_status = st.selectbox("New status", CORRECTABLE, format_func=lambda s: plain_status(STATUS_LABEL[s]))
        reason = st.text_input("Reason (required)", key=f"corr_reason_{session_id}", placeholder="For example: arrived late, bus delay")
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
    section("Correction history", "Every change, who it affected and why. Undone corrections stay listed.")
    st.dataframe(
        [{"#": c["correction_id"], "Student": c["attendance_records"]["students"]["name"], "From": plain_status(c["old_status"]), "To": plain_status(c["new_status"]),
          "Reason": c["reason"], "When": format_local(c["created_at"]), "Undone": "Undone" if c["reverted_at"] else ""} for c in corrections],
        width="stretch", hide_index=True,
    )
    undoable = session_service.undoable_corrections(corrections)
    if undoable:
        options = {f"#{c['correction_id']}, {c['attendance_records']['students']['name']}: {plain_status(c['old_status'])} to {plain_status(c['new_status'])}": c["correction_id"] for c in undoable}
        pick = st.selectbox("Undo a correction", list(options), key=f"undo_pick_{session_id}")
        if st.button("Undo selected correction", icon=":material/undo:", key=f"undo_{session_id}"):
            cid = options[pick]
            confirm_dialog("Undo this correction?", "The student's status goes back to what it was before this correction. The undo is added to the audit trail; the original correction stays listed.",
                           "Undo correction", lambda: session_service.undo_correction(teacher_id, cid), key=f"undo_{session_id}_dlg", success="Correction undone")
