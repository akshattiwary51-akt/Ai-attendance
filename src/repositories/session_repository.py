"""Attendance sessions, records and corrections. Mutations are DB functions (atomic + audited)."""
from __future__ import annotations

from typing import Iterable

from src.repositories._base import call_rpc, chunked, execute, fetch_all, table

_SESSION_COLS = "session_id, subject_id, teacher_id, method, status, location, started_at, ended_at, subjects(name, subject_code)"


# ── mutations ──
# The acting teacher is taken from the caller's JWT inside the DB function - never passed as a parameter.
def create(subject_id: int, method: str, location: str | None = None) -> int:
    return int(call_rpc("create_attendance_session", {"p_subject_id": subject_id, "p_method": method, "p_location": location}))


def complete(session_id: int, records: list[dict]) -> int:
    return int(call_rpc("complete_attendance_session", {"p_session_id": session_id, "p_records": records}))


def set_recognition_stats(session_id: int, stats: dict) -> None:
    call_rpc("set_session_recognition_stats", {"p_session_id": session_id, "p_stats": stats})


def cancel(session_id: int) -> None:
    call_rpc("cancel_attendance_session", {"p_session_id": session_id})


def reopen(session_id: int) -> None:
    call_rpc("reopen_attendance_session", {"p_session_id": session_id})


def correct(session_id: int, student_id: int, new_status: str, reason: str) -> int:
    return int(call_rpc("correct_attendance_record", {
        "p_session_id": session_id, "p_student_id": student_id, "p_new_status": new_status, "p_reason": reason,
    }))


def undo_correction(correction_id: int) -> None:
    call_rpc("undo_attendance_correction", {"p_correction_id": correction_id})


# ── reads ──
def get(session_id: int) -> dict | None:
    rows = execute(table("attendance_sessions").select(_SESSION_COLS).eq("session_id", session_id).limit(1), "session.get")
    return rows[0] if rows else None


def find_open(subject_id: int) -> dict | None:
    rows = execute(table("attendance_sessions").select(_SESSION_COLS).eq("subject_id", subject_id).eq("status", "OPEN").limit(1), "session.find_open")
    return rows[0] if rows else None


def list_for_teacher(teacher_id: int) -> list[dict]:
    return fetch_all(
        lambda: table("attendance_sessions").select(_SESSION_COLS).eq("teacher_id", teacher_id).order("started_at", desc=True).order("session_id", desc=True),
        "session.list_for_teacher",
    )


def completed_session_subjects(subject_ids: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    for ids in chunked(subject_ids):
        rows += fetch_all(
            lambda ids=ids: table("attendance_sessions").select("session_id, subject_id").in_("subject_id", ids).eq("status", "COMPLETED").order("session_id"),
            "session.completed_subjects",
        )
    return rows


def records_for_sessions(session_ids: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    for ids in chunked(session_ids):
        rows += fetch_all(
            lambda ids=ids: table("attendance_records").select("record_id, session_id, status").in_("session_id", ids).order("record_id"),
            "session.records_for_sessions",
        )
    return rows


def records(session_id: int) -> list[dict]:
    return fetch_all(
        lambda: table("attendance_records")
        .select("student_id, status, reason, source, confidence, manually_corrected, students(name)")
        .eq("session_id", session_id)
        .order("student_id"),
        "session.records",
    )


def corrections(session_id: int) -> list[dict]:
    return fetch_all(
        lambda: table("attendance_corrections")
        .select("correction_id, record_id, old_status, new_status, reason, created_at, reverted_at, attendance_records!inner(session_id, student_id, students(name))")
        .eq("attendance_records.session_id", session_id)
        .order("correction_id", desc=True),
        "session.corrections",
    )
