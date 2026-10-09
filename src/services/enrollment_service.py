from __future__ import annotations

from enum import Enum

from src.repositories import enrollment_repository
from src.utils.errors import ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)


class EnrollOutcome(str, Enum):
    ENROLLED = "ENROLLED"
    ALREADY_ENROLLED = "ALREADY_ENROLLED"
    NOT_FOUND = "NOT_FOUND"


def _code(code: str) -> str:
    code = (code or "").strip()
    if not code:
        raise ValidationError("empty code", user_message="Please enter a subject code.")
    return code


def preview_subject(code: str) -> dict | None:
    """{subject_id, name, section, enrolled} for the code, or None if no such subject."""
    return enrollment_repository.preview_subject(_code(code))


def enroll_by_code(code: str) -> tuple[EnrollOutcome, dict | None]:
    """Enrol the logged-in student (identity from the JWT); idempotent."""
    result = enrollment_repository.enroll_by_code(_code(code)) or {"outcome": "NOT_FOUND"}
    outcome = EnrollOutcome(result["outcome"])
    if outcome is EnrollOutcome.NOT_FOUND:
        return outcome, None
    if outcome is EnrollOutcome.ENROLLED:
        log_event(log, "student_enrolled", subject_id=result["subject_id"])
    return outcome, {k: result.get(k) for k in ("subject_id", "name", "section")}


def unenroll(student_id: int, subject_id: int) -> None:
    enrollment_repository.remove(student_id, subject_id)
    log_event(log, "student_unenrolled", student_id=student_id, subject_id=subject_id)


def student_subjects(student_id: int) -> list[dict]:
    return enrollment_repository.subjects_of_student(student_id)


def subject_roster(subject_id: int) -> list[dict]:
    return enrollment_repository.students_in_subject(subject_id)
