"""Read models for dashboards (RLS-scoped views) and admin KPIs."""
from __future__ import annotations

from typing import Iterable

from src.repositories._base import call_rpc, chunked, fetch_all, table


def subject_student_attendance(subject_ids: Iterable[int] | None = None) -> list[dict]:
    """Per (subject, student): attended / conducted / excused counts from COMPLETED sessions.
    The view runs as the caller, so a student only ever receives their own rows."""
    if subject_ids is None:
        return fetch_all(lambda: table("v_subject_student_attendance").select("*").order("subject_id").order("student_id"), "analytics.attendance")
    rows: list[dict] = []
    for ids in chunked(subject_ids):
        rows += fetch_all(
            lambda ids=ids: table("v_subject_student_attendance").select("*").in_("subject_id", ids).order("subject_id").order("student_id"),
            "analytics.attendance",
        )
    return rows


def session_summaries(subject_id: int | None = None) -> list[dict]:
    """Per-session present/late/absent/excused tallies, newest first (teacher/admin only; students get nothing)."""
    def query():
        q = table("v_session_summary").select("*")
        if subject_id is not None:
            q = q.eq("subject_id", subject_id)
        return q.order("started_at", desc=True).order("session_id", desc=True)
    return fetch_all(query, "analytics.sessions")


def set_subject_target(subject_id: int, target: float) -> None:
    call_rpc("set_subject_target", {"p_subject_id": subject_id, "p_target": target})


def admin_overview(tz: str) -> dict:
    return call_rpc("admin_overview", {"p_tz": tz})


def sessions_detail(subject_ids: Iterable[int] | None = None) -> list[dict]:
    """Sessions with times and recognition stats (RLS-scoped): the input of anomaly detection and the heatmap."""
    cols = "session_id, subject_id, teacher_id, method, status, started_at, ended_at, recognition_stats"
    if subject_ids is None:
        return fetch_all(lambda: table("attendance_sessions").select(cols).order("started_at").order("session_id"), "analytics.sessions_detail")
    rows: list[dict] = []
    for ids in chunked(subject_ids):
        rows += fetch_all(lambda ids=ids: table("attendance_sessions").select(cols).in_("subject_id", ids).order("started_at").order("session_id"),
                          "analytics.sessions_detail")
    return rows


def records_for_sessions(session_ids: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    for ids in chunked(session_ids):
        rows += fetch_all(lambda ids=ids: table("attendance_records").select("record_id, session_id, student_id, status, source, confidence")
                          .in_("session_id", ids).order("record_id"), "analytics.records")
    return rows


def corrections_for_records(record_ids: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    for ids in chunked(record_ids):
        rows += fetch_all(lambda ids=ids: table("attendance_corrections").select("correction_id, record_id, old_status, new_status, corrected_by, created_at, reverted_at")
                          .in_("record_id", ids).order("correction_id"), "analytics.corrections")
    return rows
