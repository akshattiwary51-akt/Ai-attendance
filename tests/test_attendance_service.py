import pytest

from src.repositories import attendance_repository
from src.services import attendance_service as svc
from src.services.attendance_service import Detection

ROSTER = [{"student_id": 1, "name": "A"}, {"student_id": 2, "name": "B"}, {"student_id": 3, "name": "C"}]


def test_build_rows_one_per_student_with_present_absent():
    display, records = svc.build_attendance_rows(ROSTER, {2: Detection(2, "Photo 1, Photo 3", 0.9)})
    assert [r["status"] for r in records] == ["ABSENT", "PRESENT", "ABSENT"]
    assert [r["Status"] for r in display] == ["❌ Absent", "✅ Present", "❌ Absent"]
    assert display[1]["Source"] == "Photo 1, Photo 3" and records[1]["confidence"] == 0.9 and len(records) == 3
    assert set(records[0]) == {"student_id", "status", "source", "confidence"}


def test_build_rows_empty_roster():
    assert svc.build_attendance_rows([], {}) == ([], [])


def row(subject, status):
    return {"status": status, "attendance_sessions": {"subject_id": subject}}


def test_stats_count_present_and_late_as_attended_and_ignore_excused():
    rows = [row(1, "PRESENT"), row(1, "LATE"), row(1, "ABSENT"), row(1, "EXCUSED"), row(2, "ABSENT"), row(3, "EXCUSED")]
    stats = svc.student_subject_stats(rows)
    assert stats[1] == {"total": 3, "attended": 2, "percentage": 66.7}          # excused is neutral
    assert stats[2]["percentage"] == 0.0 and 3 not in stats


def test_percentage_handles_zero_total():
    assert svc.percentage(0, 0) == 0.0 and svc.percentage(3, 4) == 75.0


def test_get_student_stats_reads_repository(monkeypatch):
    monkeypatch.setattr(attendance_repository, "list_for_student", lambda sid: [row(5, "PRESENT")])
    assert svc.get_student_stats(1)[5]["percentage"] == 100.0
