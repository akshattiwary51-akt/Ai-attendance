"""Dashboard service with stubbed repositories: aggregation, ordering, 'today' in the display timezone, ownership."""
from datetime import datetime, timezone

import pytest

from src.repositories import analytics_repository as ar, attendance_repository, enrollment_repository
from src.services import dashboard_service as ds, subject_service
from src.utils.errors import NotFoundError, ValidationError


def row(sid, stu, a, c, ex=0):
    return {"subject_id": sid, "student_id": stu, "attended": a, "conducted": c, "excused": ex, "last_session_at": None}


@pytest.fixture
def stub(monkeypatch):
    subs = [{"subject_id": 1, "subject_code": "A1", "name": "Algo", "section": "A", "target_percent": 75.0, "total_students": 3, "total_classes": 4},
            {"subject_id": 2, "subject_code": "B1", "name": "Bio", "section": "A", "target_percent": 80.0, "total_students": 1, "total_classes": 0}]
    monkeypatch.setattr(subject_service, "list_teacher_subjects", lambda t: subs)
    monkeypatch.setattr(enrollment_repository, "rosters", lambda ids: [
        {"subject_id": 1, "students": {"student_id": 10, "name": "Zed"}}, {"subject_id": 1, "students": {"student_id": 11, "name": "Amy"}},
        {"subject_id": 1, "students": {"student_id": 12, "name": "Bob"}}, {"subject_id": 2, "students": {"student_id": 10, "name": "Zed"}}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [row(1, 10, 1, 4), row(1, 11, 4, 4), row(1, 12, 3, 4)])
    sessions = [
        {"session_id": 3, "subject_id": 1, "started_at": "2026-03-10T20:00:00+00:00", "status": "COMPLETED", "method": "FACE", "present": 3, "late": 0, "absent": 1, "excused": 0, "conducted": 4},
        {"session_id": 2, "subject_id": 1, "started_at": "2026-03-09T05:00:00+00:00", "status": "CANCELLED", "method": "FACE", "present": 0, "late": 0, "absent": 0, "excused": 0, "conducted": 0},
        {"session_id": 1, "subject_id": 1, "started_at": "2026-03-08T05:00:00+00:00", "status": "COMPLETED", "method": "VOICE", "present": 2, "late": 0, "absent": 2, "excused": 0, "conducted": 4}]
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [s for s in sessions if subject_id in (None, s["subject_id"])])
    return subs


def test_teacher_overview_aggregates_and_orders_risk(stub):
    ov = ds.teacher_overview(1, now=datetime(2026, 3, 11, 0, 0, tzinfo=timezone.utc))
    assert (ov.total_subjects, ov.total_students) == (2, 3)
    assert ov.average_attendance == 66.7          # (1+4+3)/12
    assert ov.at_risk[0]["name"] == "Zed" and ov.at_risk[0]["risk"] == "HIGH"
    assert ov.low_attendance_students == 1
    assert [r["session_id"] for r in ov.recent_sessions][:1] == [3]


def test_sessions_today_uses_display_timezone_and_skips_cancelled(stub, monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    from src.config import settings
    settings.get_settings.cache_clear() if hasattr(settings.get_settings, "cache_clear") else None
    # 20:00 UTC on 10 Mar is 01:30 on 11 Mar in Kolkata
    assert ds.teacher_overview(1, now=datetime(2026, 3, 11, 3, 0, tzinfo=timezone.utc)).sessions_today == 1
    assert ds.teacher_overview(1, now=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)).sessions_today == 0
    settings.get_settings.cache_clear() if hasattr(settings.get_settings, "cache_clear") else None


def test_subject_detail_roster_trend_and_ownership(stub):
    d = ds.subject_detail(1, 1)
    assert [s["name"] for s in d["students"]] == ["Amy", "Bob", "Zed"]
    assert [t["percentage"] for t in d["trend"]] == [50.0, 75.0]          # oldest first, cancelled excluded
    assert d["at_risk"][0]["name"] == "Zed"
    with pytest.raises(NotFoundError):
        ds.subject_detail(1, 99)


def test_students_overview_combines_subjects(stub):
    zed = next(p for p in ds.students_overview(1) if p["name"] == "Zed")
    assert len(zed["subjects"]) == 2 and zed["attended"] == 1 and zed["conducted"] == 4 and zed["risk"] == "HIGH"


def test_student_overview_ignores_foreign_rows_and_handles_no_subjects(monkeypatch):
    monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda s: [])
    monkeypatch.setattr(attendance_repository, "list_for_student", lambda s: [])
    ov = ds.student_overview(5)
    assert ov.subjects == [] and ov.conducted == 0 and ov.risk == "NO_DATA"
    monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda s: [{"subject_id": 1, "target_percent": 75}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [row(1, 999, 0, 10), row(1, 5, 9, 10)])
    ov = ds.student_overview(5)
    assert (ov.attended, ov.conducted, ov.overall_percentage) == (9, 10, 90.0)


@pytest.mark.parametrize("bad", [0, -1, 101, float("nan"), "x", None])
def test_set_target_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        subject_service.set_target(1, bad)


def test_set_target_rounds_and_delegates(monkeypatch):
    got = []
    monkeypatch.setattr(ar, "set_subject_target", lambda sid, t: got.append((sid, t)))
    subject_service.set_target(3, 82.456)
    assert got == [(3, 82.46)]
