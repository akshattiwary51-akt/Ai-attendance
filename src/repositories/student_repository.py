from __future__ import annotations

from typing import Any, Iterable

from src.repositories._base import chunked, fetch_all, table


def _active_profiles(profile_table: str, student_ids: Iterable[int] | None) -> list[dict]:
    action = f"student.{profile_table}"
    base = lambda: table(profile_table).select("student_id, embedding").eq("is_active", True).order("profile_id")  # noqa: E731
    if student_ids is None:
        return fetch_all(base, action)
    rows: list[dict] = []
    for ids in chunked(student_ids):
        rows += fetch_all(lambda ids=ids: base().in_("student_id", ids), action)
    return rows


def get_face_gallery(student_ids: Iterable[int] | None = None) -> dict[int, list[Any]]:
    """{student_id: [embedding, ...]} - active face samples. RLS: a teacher only receives students enrolled in their subjects."""
    gallery: dict[int, list[Any]] = {}
    for row in _active_profiles("face_profiles", student_ids):
        gallery.setdefault(row["student_id"], []).append(row["embedding"])
    return gallery


def get_voice_gallery(student_ids: Iterable[int] | None = None) -> dict[int, Any]:
    """{student_id: embedding} - one active voice profile per student."""
    return {row["student_id"]: row["embedding"] for row in _active_profiles("voice_profiles", student_ids)}
