from __future__ import annotations

from src.repositories._base import execute, fetch_all, table


def list_for_teacher(teacher_id: int) -> list[dict]:
    return fetch_all(
        lambda: table("subjects")
        .select("subject_id, subject_code, name, section, enrollments(count)")
        .eq("teacher_id", teacher_id)
        .order("subject_id"),
        "subject.list_for_teacher",
    )


def create(subject_code: str, name: str, section: str, teacher_id: int) -> dict:
    rows = execute(
        table("subjects").insert({"subject_code": subject_code, "name": name, "section": section, "teacher_id": teacher_id}),
        "subject.create",
    )
    return rows[0]
