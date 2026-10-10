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
