from __future__ import annotations

from src.repositories._base import call_rpc, execute, fetch_all, table


def preview_subject(code: str) -> dict | None:
    """{subject_id, name, section, enrolled} for a subject code, or None (DB function; identity from JWT)."""
    return call_rpc("preview_subject", {"p_code": code})


def enroll_by_code(code: str) -> dict:
    """{outcome: ENROLLED|ALREADY_ENROLLED|NOT_FOUND, subject_id?, name?, section?} - student only."""
    return call_rpc("enroll_by_code", {"p_code": code})


def remove(student_id: int, subject_id: int) -> None:
    """RLS limits this to the student's own enrolment or a teacher's own subject."""
    execute(table("enrollments").delete().eq("student_id", student_id).eq("subject_id", subject_id), "enrollment.remove")


def students_in_subject(subject_id: int) -> list[dict]:
    """Enrolled, active students as [{student_id, name}] - no biometric columns."""
    rows = fetch_all(
        lambda: table("enrollments").select("student_id, students!inner(student_id, name)").eq("subject_id", subject_id).eq("students.is_active", True).order("student_id"),
        "enrollment.students_in_subject",
    )
    return [r["students"] for r in rows if r.get("students")]


def subjects_of_student(student_id: int) -> list[dict]:
    rows = fetch_all(
        lambda: table("enrollments").select("subjects(subject_id, subject_code, name, section)").eq("student_id", student_id).order("subject_id"),
        "enrollment.subjects_of_student",
    )
    return [r["subjects"] for r in rows if r.get("subjects")]
