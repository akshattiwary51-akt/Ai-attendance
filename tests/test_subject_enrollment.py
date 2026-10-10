import pytest

from src.repositories import enrollment_repository, session_repository, subject_repository
from src.services import enrollment_service, subject_service
from src.services.enrollment_service import EnrollOutcome
from src.utils.errors import DuplicateError, ValidationError


def test_list_teacher_subjects_returns_all_subjects_with_counts(monkeypatch):
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [
        {"subject_id": 1, "subject_code": "A", "name": "A", "section": "x", "enrollments": [{"count": 5}]},
        {"subject_id": 2, "subject_code": "B", "name": "B", "section": "y", "enrollments": []},
        {"subject_id": 3, "subject_code": "C", "name": "C", "section": "z", "enrollments": [{"count": 1}]},
    ])
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [
        {"subject_id": 1, "session_id": 10}, {"subject_id": 1, "session_id": 10}, {"subject_id": 1, "session_id": 11},
    ])
    out = subject_service.list_teacher_subjects(9)
    assert [s["subject_id"] for s in out] == [1, 2, 3]
    assert [s["total_students"] for s in out] == [5, 0, 1]
    assert [s["total_classes"] for s in out] == [2, 0, 0]       # distinct completed sessions


def test_empty_teacher_has_no_subjects(monkeypatch):
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [])
    assert subject_service.list_teacher_subjects(1) == []


def test_create_subject_validation_and_db_duplicate_code(monkeypatch):
    created = []
    def create(c, n, s, t, target=75.0):
        if c == "TAKEN":
            raise DuplicateError("dup")
        created.append(c); return {"subject_id": 2}
    monkeypatch.setattr(subject_repository, "create", create)
    subject_service.create_subject(1, " CS101 ", "Intro", "A")
    assert created == ["CS101"]
    for args in [("", "n", "s"), ("TAKEN", "n", "s"), ("bad code!", "n", "s"), ("OK1", "", "s")]:
        with pytest.raises(ValidationError):
            subject_service.create_subject(1, *args)


def test_enroll_by_code_maps_db_outcomes(monkeypatch):
    results = iter([{"outcome": "ENROLLED", "subject_id": 10, "name": "DSA", "section": "A"},
                    {"outcome": "ALREADY_ENROLLED", "subject_id": 10, "name": "DSA", "section": "A"},
                    {"outcome": "NOT_FOUND"}, None])
    seen = []
    monkeypatch.setattr(enrollment_repository, "enroll_by_code", lambda code: seen.append(code) or next(results))
    assert enrollment_service.enroll_by_code(" DSA1 ") == (EnrollOutcome.ENROLLED, {"subject_id": 10, "name": "DSA", "section": "A"})
    assert enrollment_service.enroll_by_code("DSA1")[0] is EnrollOutcome.ALREADY_ENROLLED
    assert enrollment_service.enroll_by_code("NOPE") == (EnrollOutcome.NOT_FOUND, None)
    assert enrollment_service.enroll_by_code("NONE") == (EnrollOutcome.NOT_FOUND, None)      # defensive: empty DB result
    assert seen[0] == "DSA1"                                                                  # trimmed before the DB call


def test_blank_codes_are_rejected_before_the_db(monkeypatch):
    monkeypatch.setattr(enrollment_repository, "enroll_by_code", lambda c: pytest.fail("must not be called"))
    monkeypatch.setattr(enrollment_repository, "preview_subject", lambda c: pytest.fail("must not be called"))
    for fn in (enrollment_service.enroll_by_code, enrollment_service.preview_subject):
        with pytest.raises(ValidationError):
            fn("   ")


def test_preview_passes_through(monkeypatch):
    monkeypatch.setattr(enrollment_repository, "preview_subject", lambda c: {"subject_id": 1, "name": "DSA", "section": "A", "enrolled": False})
    assert enrollment_service.preview_subject("dsa1")["enrolled"] is False
