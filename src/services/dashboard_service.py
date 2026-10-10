"""Dashboard read models for students, teachers and admins (all numbers derive from RLS-scoped DB views)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from src.analytics import attendance_math as am
from src.config.settings import get_settings
from src.repositories import analytics_repository, attendance_repository, enrollment_repository
from src.services import subject_service
from src.utils.errors import NotFoundError
from src.utils.timefmt import local_tz, parse_ts


@dataclass(frozen=True)
class Standing:
    """One student's position in one subject."""
    subject_id: int
    attended: int
    conducted: int
    excused: int
    target: float
    percentage: float
    can_miss: int
    to_recover: int | None
    risk: str
    reasons: tuple[str, ...]
    last_session_at: str | None = None


def make_standing(subject_id: int, attended: int, conducted: int, excused: int, target: float, last: str | None = None) -> Standing:
    risk = am.assess_risk(attended, conducted, target, get_settings().risk_buffer)
    return Standing(subject_id, attended, conducted, excused, target, am.percentage(attended, conducted),
                    am.classes_can_miss(attended, conducted, target), am.classes_to_recover(attended, conducted, target),
                    risk.level, risk.reasons, last)


def _row_standing(row: dict | None, subject_id: int, target: float) -> Standing:
    row = row or {"attended": 0, "conducted": 0, "excused": 0, "last_session_at": None}
    return make_standing(subject_id, row["attended"], row["conducted"], row["excused"], target, row.get("last_session_at"))


_RISK_ORDER = {am.HIGH: 0, am.MEDIUM: 1, am.LOW: 2, am.NO_DATA: 3}


# ───────────────────────── student ─────────────────────────
@dataclass(frozen=True)
class StudentOverview:
    overall_percentage: float
    attended: int
    missed: int
    conducted: int
    risk: str
    streak: int
    subjects: list[tuple[dict, Standing]] = field(default_factory=list)


def student_overview(student_id: int) -> StudentOverview:
    subjects = enrollment_repository.subjects_of_student(student_id)
    view_rows = analytics_repository.subject_student_attendance([s["subject_id"] for s in subjects]) if subjects else []
    by_subject = {r["subject_id"]: r for r in view_rows if r["student_id"] == student_id}   # ignore any foreign row defensively
    rows = [(s, _row_standing(by_subject.get(s["subject_id"]), s["subject_id"], float(s.get("target_percent") or 75))) for s in subjects]
    attended, conducted = sum(st.attended for _, st in rows), sum(st.conducted for _, st in rows)
    records = sorted(attendance_repository.list_for_student(student_id),
                     key=lambda r: (r["attendance_sessions"]["started_at"], r["record_id"]), reverse=True)
    return StudentOverview(
        overall_percentage=am.percentage(attended, conducted), attended=attended, missed=conducted - attended, conducted=conducted,
        risk=am.worst(st.risk for _, st in rows), streak=am.current_streak(r["status"] for r in records), subjects=rows,
    )


# ───────────────────────── teacher ─────────────────────────
@dataclass(frozen=True)
class TeacherOverview:
    total_subjects: int
    total_students: int
    sessions_today: int
    average_attendance: float | None
    low_attendance_students: int
    recent_sessions: list[dict]
    at_risk: list[dict]            # [{student_id, name, subject, percentage, risk, reason}] worst first


def _teacher_data(teacher_id: int):
    subjects = subject_service.list_teacher_subjects(teacher_id)
    ids = [s["subject_id"] for s in subjects]
    attendance = {(r["subject_id"], r["student_id"]): r for r in analytics_repository.subject_student_attendance(ids)} if ids else {}
    rosters: dict[int, list[dict]] = defaultdict(list)
    for r in (enrollment_repository.rosters(ids) if ids else []):
        rosters[r["subject_id"]].append(r["students"])
    return subjects, attendance, rosters


def teacher_overview(teacher_id: int, now: datetime | None = None) -> TeacherOverview:
    subjects, attendance, rosters = _teacher_data(teacher_id)
    sessions = analytics_repository.session_summaries() if subjects else []
    today = (now or datetime.now(local_tz())).astimezone(local_tz()).date()
    sessions_today = sum(1 for s in sessions if s["status"] != "CANCELLED" and parse_ts(s["started_at"]).astimezone(local_tz()).date() == today)

    attended = sum(r["attended"] for r in attendance.values())
    conducted = sum(r["conducted"] for r in attendance.values())
    at_risk, low_students = [], set()
    for sub in subjects:
        for stu in rosters[sub["subject_id"]]:
            st = _row_standing(attendance.get((sub["subject_id"], stu["student_id"])), sub["subject_id"], sub["target_percent"])
            if st.risk in (am.HIGH, am.MEDIUM):
                at_risk.append({"student_id": stu["student_id"], "name": stu["name"], "subject": sub["name"], "percentage": st.percentage,
                                "risk": st.risk, "reason": st.reasons[0]})
            if st.risk == am.HIGH:
                low_students.add(stu["student_id"])
    at_risk.sort(key=lambda r: (_RISK_ORDER[r["risk"]], r["percentage"], r["name"]))
    names = {s["subject_id"]: s["name"] for s in subjects}
    recent = [{"session_id": s["session_id"], "subject": names.get(s["subject_id"], "?"), "when": s["started_at"], "status": s["status"], "method": s["method"],
               "present": s["present"] + s["late"], "conducted": s["conducted"]} for s in sessions[:5]]
    return TeacherOverview(
        total_subjects=len(subjects), total_students=len({stu["student_id"] for r in rosters.values() for stu in r}),
        sessions_today=sessions_today, average_attendance=am.percentage(attended, conducted) if conducted else None,
        low_attendance_students=len(low_students), recent_sessions=recent, at_risk=at_risk,
    )


def subject_detail(teacher_id: int, subject_id: int) -> dict:
    """Roster with standings, recent sessions, per-session attendance trend and the at-risk list for one subject."""
    subjects, attendance, rosters = _teacher_data(teacher_id)
    subject = next((s for s in subjects if s["subject_id"] == subject_id), None)
    if subject is None:
        raise NotFoundError("subject not owned", user_message="That subject was not found.")
    students = []
    for stu in sorted(rosters[subject_id], key=lambda s: s["name"].lower()):
        st = _row_standing(attendance.get((subject_id, stu["student_id"])), subject_id, subject["target_percent"])
        students.append({"student_id": stu["student_id"], "name": stu["name"], "standing": st})
    sessions = analytics_repository.session_summaries(subject_id)
    completed = [s for s in sessions if s["status"] == "COMPLETED" and s["conducted"]]
    trend = [{"when": s["started_at"], "percentage": am.percentage(s["present"] + s["late"], s["conducted"])} for s in reversed(completed)]
    return {
        "subject": subject, "students": students, "sessions": sessions[:10], "trend": trend,
        "at_risk": sorted((s for s in students if s["standing"].risk in (am.HIGH, am.MEDIUM)),
                          key=lambda s: (_RISK_ORDER[s["standing"].risk], s["standing"].percentage)),
    }


def students_overview(teacher_id: int) -> list[dict]:
    """One row per student across the teacher's subjects (overall %, worst risk, per-subject breakdown)."""
    subjects, attendance, rosters = _teacher_data(teacher_id)
    people: dict[int, dict] = {}
    for sub in subjects:
        for stu in rosters[sub["subject_id"]]:
            st = _row_standing(attendance.get((sub["subject_id"], stu["student_id"])), sub["subject_id"], sub["target_percent"])
            p = people.setdefault(stu["student_id"], {"student_id": stu["student_id"], "name": stu["name"], "subjects": [], "attended": 0, "conducted": 0})
            p["subjects"].append((sub["name"], st)); p["attended"] += st.attended; p["conducted"] += st.conducted
    for p in people.values():
        p["percentage"] = am.percentage(p["attended"], p["conducted"]); p["risk"] = am.worst(st.risk for _, st in p["subjects"])
    return sorted(people.values(), key=lambda p: (_RISK_ORDER[p["risk"]], p["percentage"], p["name"].lower()))


# ───────────────────────── admin ─────────────────────────
def admin_overview() -> dict:
    return analytics_repository.admin_overview(get_settings().app_timezone)
