"""Attendance-session workflow: start → (AI recognition) → review → confirm → correct/undo/reopen."""
from __future__ import annotations

import pandas as pd

from src.repositories import session_repository
from src.services.attendance_service import ATTENDED, COUNTED, STATUS_LABEL
from src.utils.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from src.utils.logging import get_logger, log_event
from src.utils.timefmt import format_local

log = get_logger(__name__)
METHODS = ("FACE", "VOICE", "FACE_PLUS_VOICE", "MANUAL")


def _check_method(method: str) -> None:
    if method not in METHODS:
        raise ValidationError("bad method", user_message="Unknown attendance method.")


def get_owned_session(teacher_id: int, session_id: int) -> dict:
    session = session_repository.get(session_id)
    if session is None:
        raise NotFoundError("session missing", user_message="That attendance session was not found.")
    if session["teacher_id"] != teacher_id:
        raise AuthorizationError("not owner")
    return session


def find_open(teacher_id: int, subject_id: int) -> dict | None:
    session = session_repository.find_open(subject_id)
    if session and session["teacher_id"] != teacher_id:
        raise AuthorizationError("not owner")
    return session


def get_or_start(teacher_id: int, subject_id: int, method: str) -> dict:
    """Reuse the subject's open session (same method) or start one - never creates a duplicate."""
    _check_method(method)
    open_session = find_open(teacher_id, subject_id)
    if open_session:
        if open_session["method"] != method:
            raise ConflictError("method mismatch", user_message=f"A {open_session['method']} session is already open for this subject. Finish or cancel it first.")
        return open_session
    try:
        session_id = session_repository.create(subject_id, method)
    except ConflictError:  # lost a race with another tab/device: use the winner
        existing = find_open(teacher_id, subject_id)
        if existing and existing["method"] == method:
            return existing
        raise
    log_event(log, "session_started", session_id=session_id, subject_id=subject_id, method=method)
    return get_owned_session(teacher_id, session_id)


def confirm(teacher_id: int, session_id: int, records: list[dict]) -> int:
    """Save results and close the session. Returns rows inserted (0 if it was already saved)."""
    try:
        inserted = session_repository.complete(session_id, records)
    except ConflictError:
        if get_owned_session(teacher_id, session_id)["status"] == "COMPLETED":
            return 0  # double click / rerun: already saved
        raise
    log_event(log, "attendance_confirmed", session_id=session_id, inserted=inserted)
    return inserted


def discard(teacher_id: int, session_id: int) -> None:
    try:
        session_repository.cancel(session_id)
    except ConflictError:
        if get_owned_session(teacher_id, session_id)["status"] != "CANCELLED":
            raise
    log_event(log, "session_cancelled", session_id=session_id)


def reopen(teacher_id: int, session_id: int) -> None:
    session_repository.reopen(session_id)
    log_event(log, "session_reopened", session_id=session_id)


def correct_record(teacher_id: int, session_id: int, student_id: int, new_status: str, reason: str) -> int:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("reason", user_message="Please give a reason for the correction.")
    correction_id = session_repository.correct(session_id, student_id, new_status, reason)
    log_event(log, "attendance_corrected", session_id=session_id, student_id=student_id, new_status=new_status)
    return correction_id


def undo_correction(teacher_id: int, correction_id: int) -> None:
    session_repository.undo_correction(correction_id)
    log_event(log, "correction_undone", correction_id=correction_id)


def session_detail(teacher_id: int, session_id: int) -> dict:
    """Session + records + corrections (read access limited to the owning teacher)."""
    session = get_owned_session(teacher_id, session_id)
    records = session_repository.records(session_id)
    corrections = session_repository.corrections(session_id)
    return {"session": session, "records": records, "corrections": corrections}


def undoable_corrections(corrections: list[dict]) -> list[dict]:
    """The latest not-yet-undone correction per record (the only ones the DB allows undoing)."""
    latest: dict[int, dict] = {}
    for c in corrections:
        if c["reverted_at"] is None and (c["record_id"] not in latest or c["correction_id"] > latest[c["record_id"]]["correction_id"]):
            latest[c["record_id"]] = c
    return sorted(latest.values(), key=lambda c: -c["correction_id"])


_EMPTY = ["ID", "Time", "Subject", "Subject Code", "Method", "Status", "Attendance"]


def list_sessions(teacher_id: int) -> pd.DataFrame:
    """One row per session, newest first, with present/counted tallies."""
    sessions = session_repository.list_for_teacher(teacher_id)
    if not sessions:
        return pd.DataFrame(columns=_EMPTY)
    tally: dict[int, list[int]] = {}
    for r in session_repository.records_for_sessions([s["session_id"] for s in sessions]):
        if r["status"] in COUNTED:
            t = tally.setdefault(r["session_id"], [0, 0])
            t[0] += r["status"] in ATTENDED
            t[1] += 1
    rows = []
    for s in sessions:
        present, total = tally.get(s["session_id"], [0, 0])
        rows.append({
            "ID": s["session_id"], "Time": format_local(s["started_at"]), "Subject": s["subjects"]["name"],
            "Subject Code": s["subjects"]["subject_code"], "Method": s["method"], "Status": s["status"],
            "Attendance": f"✅ {present} / {total}" if s["status"] != "OPEN" else "in progress",
        })
    return pd.DataFrame(rows, columns=_EMPTY)


def records_table(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {"ID": r["student_id"], "Name": r["students"]["name"], "Status": STATUS_LABEL.get(r["status"], r["status"]),
         "Reason": r["reason"] or "", "Source": r["source"] or "", "Confidence": r["confidence"], "Corrected": "✏️" if r["manually_corrected"] else ""}
        for r in records
    ], columns=["ID", "Name", "Status", "Reason", "Source", "Confidence", "Corrected"])
