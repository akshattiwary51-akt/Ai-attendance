"""Attendance result building and student statistics (pure logic + one repository read)."""
from __future__ import annotations

from dataclasses import dataclass

from src.repositories import attendance_repository

PRESENT, LATE, ABSENT, EXCUSED, UNKNOWN, REJECTED = "PRESENT", "LATE", "ABSENT", "EXCUSED", "UNKNOWN", "REJECTED"
ATTENDED = frozenset({PRESENT, LATE})          # counts as having attended
COUNTED = frozenset({PRESENT, LATE, ABSENT})   # counts toward classes conducted (EXCUSED is neutral)
CORRECTABLE = (PRESENT, LATE, ABSENT, EXCUSED)
STATUS_LABEL = {PRESENT: "✅ Present", LATE: "🕒 Late", ABSENT: "❌ Absent", EXCUSED: "📝 Excused", UNKNOWN: "❓ Unknown", REJECTED: "⛔ Rejected"}


@dataclass(frozen=True)
class Detection:
    student_id: int
    source: str
    confidence: float | None = None


def build_attendance_rows(roster: list[dict], detections: dict[int, Detection]) -> tuple[list[dict], list[dict]]:
    """(display_rows, records) with exactly one entry per enrolled student."""
    display, records = [], []
    for student in roster:
        det = detections.get(student["student_id"])
        status = PRESENT if det else ABSENT
        display.append(
            {"Name": student["name"], "ID": student["student_id"], "Source": det.source if det else "-",
             "Confidence": det.confidence if det else None, "Status": STATUS_LABEL[status]}
        )
        records.append({"student_id": student["student_id"], "status": status,
                        "source": det.source if det else None, "confidence": det.confidence if det else None})
    return display, records


def percentage(attended: int, total: int) -> float:
    return round(100.0 * attended / total, 1) if total else 0.0


def student_subject_stats(rows: list[dict]) -> dict[int, dict[str, float]]:
    """{subject_id: {total, attended, percentage}} from record rows joined with their session."""
    stats: dict[int, dict[str, float]] = {}
    for row in rows:
        if row["status"] not in COUNTED:
            continue
        s = stats.setdefault(row["attendance_sessions"]["subject_id"], {"total": 0, "attended": 0})
        s["total"] += 1
        s["attended"] += row["status"] in ATTENDED
    for s in stats.values():
        s["percentage"] = percentage(s["attended"], s["total"])
    return stats


def get_student_stats(student_id: int) -> dict[int, dict[str, float]]:
    return student_subject_stats(attendance_repository.list_for_student(student_id))
