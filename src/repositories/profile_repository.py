from __future__ import annotations

from src.repositories._base import execute, table


def get_own_profile(user_id: str) -> dict | None:
    """The caller's profile with display name (RLS: a user can always read their own row)."""
    rows = execute(
        table("profiles").select("user_id, role, teacher_id, student_id, is_active, teachers(name), students(name)").eq("user_id", user_id).limit(1),
        "profile.get_own",
    )
    return rows[0] if rows else None
