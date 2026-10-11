"""Review step of the attendance flow: shows what was recognised and lets the teacher save or discard.

Nothing is written until the teacher presses Confirm and save. The session id, the idempotent ``confirm`` call and the
audited services are unchanged; this module is presentation plus a double-submit guard.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from src.services import session_service
from src.ui.feedback import show_error
from src.ui.widgets import confidence_config, note, plain_status, section, status_text, summary_chips
from src.utils.errors import AppError

REVIEW_KEY = "attendance_review"
FLASH_KEY = "attendance_flash"
_SAVING = "attendance_saving"


def reset_attendance_state() -> None:
    for key in (REVIEW_KEY, _SAVING):
        st.session_state.pop(key, None)
    st.session_state.attendance_images = []


def start_review(df: pd.DataFrame, records: list[dict], session_id: int, subject_id: int, kind: str, notes=()) -> None:
    """Store the analysis result for the review step. The caller reruns."""
    st.session_state[REVIEW_KEY] = {"df": df, "records": records, "session_id": session_id, "subject_id": subject_id, "kind": kind, "notes": list(notes)}


def current_review() -> dict | None:
    return st.session_state.get(REVIEW_KEY)


def review_table(df: pd.DataFrame) -> pd.DataFrame:
    """Display copy of the result table: readable statuses, no internal ids, confidence only when the pipeline gave one."""
    out = df.drop(columns=[c for c in ("ID",) if c in df.columns]).copy()
    out["Status"] = [status_text(plain_status(s).upper()) for s in df["Status"]]
    if "Confidence" in out and out["Confidence"].isna().all():
        out = out.drop(columns=["Confidence"])
    return out


def _counts(records: list[dict]) -> Counter:
    return Counter(r["status"] for r in records)


@st.dialog("Discard this attendance session?")
def _confirm_discard(teacher_id: int, session_id: int) -> None:
    st.write("The session will be cancelled and none of these results will be saved. You can start again from the photos or recording.")
    c1, c2 = st.columns(2)
    if c1.button("Keep reviewing", width="stretch", key="discard_keep"):
        st.rerun()
    if c2.button("Discard session", width="stretch", type="primary", key="discard_confirm"):
        try:
            session_service.discard(teacher_id, session_id)
        except AppError as exc:
            show_error(exc)
            return
        reset_attendance_state()
        st.toast("Session discarded")
        st.rerun()


def _save(teacher_id: int, review: dict) -> None:
    sid = review["session_id"]
    if st.session_state.get(_SAVING) == sid:       # a second click while the first is still being processed
        return
    st.session_state[_SAVING] = sid
    counts = _counts(review["records"])
    try:
        with st.spinner("Saving attendance…"):
            inserted = session_service.confirm(teacher_id, sid, review["records"])
    except AppError as exc:
        st.session_state.pop(_SAVING, None)
        show_error(exc)
        return
    st.session_state[FLASH_KEY] = {"session_id": sid, "subject_id": review["subject_id"], "inserted": inserted,
                                   "present": counts.get("PRESENT", 0) + counts.get("LATE", 0), "absent": counts.get("ABSENT", 0)}
    reset_attendance_state()
    st.rerun()


def review_panel(review: dict) -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    records, df = review["records"], review["df"]
    counts = _counts(records)
    flagged = int((df["Review"] != "").sum()) if "Review" in df else 0
    section("Review the results", "Check each student. Nothing is saved until you confirm.")
    chips = [("present", counts.get("PRESENT", 0), "sc-ok"), ("late", counts.get("LATE", 0), "sc-warn"), ("absent", counts.get("ABSENT", 0), "sc-bad")]
    if counts.get("EXCUSED"):
        chips.append(("excused", counts["EXCUSED"], "sc-info"))
    if flagged:
        chips.append(("need a second look", flagged, "sc-warn"))
    st.markdown(summary_chips(chips), unsafe_allow_html=True)
    for n in review["notes"]:
        st.warning(n)
    st.dataframe(review_table(df), hide_index=True, width="stretch", column_config=confidence_config())
    st.caption("Source shows how each student was recognised. Confidence appears only when the recognition step produced a score. "
               "You can correct any student after saving; each correction needs a reason and is kept in the audit trail.")
    attended = counts.get("PRESENT", 0) + counts.get("LATE", 0)
    note(f"Saving records {attended} student{'s' if attended != 1 else ''} as present or late and {counts.get('ABSENT', 0)} as absent, "
         "then closes this session. Saving twice is safe: the second attempt changes nothing.")
    st.space("small")
    saving = st.session_state.get(_SAVING) == review["session_id"]
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Discard session", width="stretch", icon=":material/delete:", key="review_discard", disabled=saving):
            _confirm_discard(teacher_id, review["session_id"])
    with c2:
        if st.button("Confirm and save", width="stretch", type="primary", icon=":material/check:", key="review_confirm", disabled=saving):
            _save(teacher_id, review)
