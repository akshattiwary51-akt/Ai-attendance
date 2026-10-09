from __future__ import annotations

from src.repositories._base import call_rpc, execute, fetch_all, table


def list_teachers() -> list[dict]:
    return fetch_all(lambda: table("teachers").select("teacher_id, name, email, is_active, created_at").order("teacher_id"), "admin.teachers")


def list_students() -> list[dict]:
    return fetch_all(lambda: table("students").select("student_id, name, email, roll_number, is_active, created_at").order("student_id"), "admin.students")


def recent_audit(limit: int = 200) -> list[dict]:
    return execute(table("audit_logs").select("audit_id, created_at, actor_role, actor_id, action, entity_type, entity_id, details").order("audit_id", desc=True).limit(limit), "admin.audit")


def set_active(role: str, entity_id: int, active: bool) -> None:
    call_rpc("admin_set_active", {"p_role": role, "p_id": entity_id, "p_active": active})
