from __future__ import annotations

import re
from collections import defaultdict

from src.repositories import session_repository, subject_repository
from src.utils.errors import DuplicateError, ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)
_CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{2,32}$")


def list_teacher_subjects(teacher_id: int) -> list[dict]:
    """Subjects with ``total_students`` and ``total_classes`` (completed attendance sessions)."""
    subjects = subject_repository.list_for_teacher(teacher_id)
    if not subjects:
        return []
    sessions: dict[int, set[int]] = defaultdict(set)
    for row in session_repository.completed_session_subjects([s["subject_id"] for s in subjects]):
        sessions[row["subject_id"]].add(row["session_id"])
    result = []
    for s in subjects:
        embedded = s.get("enrollments") or []
        result.append(
            {
                "subject_id": s["subject_id"],
                "subject_code": s["subject_code"],
                "name": s["name"],
                "section": s["section"],
                "total_students": embedded[0].get("count", 0) if embedded else 0,
                "total_classes": len(sessions[s["subject_id"]]),
            }
        )
    return result


def create_subject(teacher_id: int, code: str, name: str, section: str) -> dict:
    code, name, section = (code or "").strip(), (name or "").strip(), (section or "").strip()
    if not (code and name and section):
        raise ValidationError("missing fields", user_message="Please fill all the fields.")
    if not _CODE_RE.match(code):
        raise ValidationError("bad code", user_message="Subject code must be 2-32 characters: letters, digits, '_' or '-'.")
    try:
        subject = subject_repository.create(code, name, section, teacher_id)
    except DuplicateError as exc:
        raise ValidationError("code exists", user_message="That subject code is already in use.") from exc
    log_event(log, "subject_created", subject_id=subject.get("subject_id"), teacher_id=teacher_id)
    return subject
