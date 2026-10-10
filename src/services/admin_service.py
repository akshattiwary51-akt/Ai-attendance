"""Admin operations (authorization is enforced by the DB: non-admins get 403 / empty results)."""
from __future__ import annotations

from src.repositories import admin_repository
from src.services import dashboard_service
from src.utils.errors import ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)


def teachers() -> list[dict]:
    return admin_repository.list_teachers()


def pending_teachers() -> list[dict]:
    return [t for t in admin_repository.list_teachers() if not t["is_active"]]


def students() -> list[dict]:
    return admin_repository.list_students()


def audit_log(limit: int = 200) -> list[dict]:
    return admin_repository.recent_audit(limit)


def set_active(role: str, entity_id: int, active: bool) -> None:
    if role not in ("TEACHER", "STUDENT"):
        raise ValidationError("role", user_message="Only teachers and students can be activated or deactivated.")
    admin_repository.set_active(role, entity_id, active)
    log_event(log, "admin_set_active", role=role, entity_id=entity_id, active=active)


def overview() -> dict:
    """System KPIs computed in the database (admin only)."""
    return dashboard_service.admin_overview()
