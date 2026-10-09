"""Student-facing attendance reads (completed sessions only)."""
from __future__ import annotations

from src.repositories._base import fetch_all, table


def list_for_student(student_id: int) -> list[dict]:
    """A student's records from COMPLETED sessions: [{status, attendance_sessions: {subject_id, started_at}}]."""
    return fetch_all(
        lambda: table("attendance_records")
        .select("record_id, status, attendance_sessions!inner(subject_id, started_at, status)")
        .eq("student_id", student_id)
        .eq("attendance_sessions.status", "COMPLETED")
        .order("record_id"),
        "attendance.list_for_student",
    )
