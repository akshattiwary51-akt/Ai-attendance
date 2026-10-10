"""Analytics read models: trends, distributions, forecasts and anomaly flags. All data is read through RLS-scoped queries, so a
student only ever sees their own data, a teacher their own subjects, an admin everything; anomaly flags never change any record."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from src.analytics import anomalies as an, attendance_math as am, forecast as fc, trends as tr
from src.config.settings import get_settings
from src.repositories import analytics_repository as ar, attendance_repository, enrollment_repository
from src.services import dashboard_service, subject_service
from src.utils.timefmt import local_tz, parse_ts

ATT = am.ATTENDED


def _epoch(value: str) -> float:
    return parse_ts(value).timestamp()


def _histories(records: list[dict], start_of: dict[int, float]) -> dict[tuple[int, int], list[int]]:
    """{(subject_id, student_id): [0/1 ...]} oldest first, from records of COMPLETED sessions (EXCUSED skipped)."""
    out: dict[tuple[int, int], list[tuple[float, int, int]]] = defaultdict(list)
    for r in records:
        if r["status"] in am.COUNTED:
            out[(r["subject_id"], r["student_id"])].append((start_of[r["session_id"]], r["session_id"], 1 if r["status"] in ATT else 0))
    return {k: [x for _, _, x in sorted(v)] for k, v in out.items()}


# ───────────────────────── student ─────────────────────────
@dataclass(frozen=True)
class StudentAnalytics:
    forecasts: list[tuple[dict, fc.Forecast]]       # (subject, forecast), highest risk first
    weekly: list[dict]
    subject_comparison: list[dict]


def student_analytics(student_id: int) -> StudentAnalytics:
    subjects = enrollment_repository.subjects_of_student(student_id)
    records = attendance_repository.list_for_student(student_id)
    by_subject: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        by_subject[r["attendance_sessions"]["subject_id"]].append(r)
    horizon = fc.DEFAULT_HORIZON_DAYS
    forecasts = []
    for sub in subjects:
        rows = sorted(by_subject.get(sub["subject_id"], []), key=lambda r: (r["attendance_sessions"]["started_at"], r["record_id"]))
        hist = [1 if r["status"] in ATT else 0 for r in rows if r["status"] in am.COUNTED]
        n, assumed = fc.classes_in_horizon([_epoch(r["attendance_sessions"]["started_at"]) for r in rows], horizon)
        forecasts.append((sub, fc.forecast(hist, float(sub.get("target_percent") or get_settings().attendance_target), n, assumed)))
    rank = {am.HIGH: 0, am.MEDIUM: 1, am.LOW: 2, am.NO_DATA: 3}
    forecasts.sort(key=lambda sf: (rank[sf[1].risk], -sf[1].prob_below_target, sf[0]["name"].lower()))
    pseudo = [{"started_at": parse_ts(r["attendance_sessions"]["started_at"]), "present": r["status"] == "PRESENT", "late": r["status"] == "LATE",
               "absent": r["status"] == "ABSENT", "excused": r["status"] == "EXCUSED", "conducted": r["status"] in am.COUNTED}
              for r in records]
    pseudo = [{k: (int(v) if isinstance(v, bool) else v) for k, v in p.items()} for p in pseudo]
    comparison = [{"subject": sub["name"], "percentage": f.current_pct, "target": f.target, "expected": f.expected_pct} for sub, f in forecasts if f.conducted]
    return StudentAnalytics(forecasts, tr.trend(pseudo, "week", local_tz()), comparison)


# ───────────────────────── teacher ─────────────────────────
@dataclass(frozen=True)
class TeacherAnalytics:
    subject: dict
    trend: list[dict]
    totals: dict
    distribution: list[dict]
    ranking: list[dict]
    class_average: float | None
    highest: dict | None
    lowest: dict | None
    participation: dict
    heatmap: list[dict]
    time_slots: list[dict]
    forecasts: list[dict]
    n_future: int
    subject_comparison: list[dict] = field(default_factory=list)


def _summaries(subject_id: int | None) -> list[dict]:
    rows = ar.session_summaries(subject_id)
    return [{**r, "started_at": parse_ts(r["started_at"])} for r in rows if r["status"] == "COMPLETED"]


def subject_comparison(teacher_id: int) -> list[dict]:
    subjects = subject_service.list_teacher_subjects(teacher_id)
    ids = [s["subject_id"] for s in subjects]
    att = ar.subject_student_attendance(ids) if ids else []
    acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for r in att:
        acc[r["subject_id"]][0] += r["attended"]; acc[r["subject_id"]][1] += r["conducted"]
    return [{"subject": s["name"], "percentage": am.percentage(*acc[s["subject_id"]]) if acc[s["subject_id"]][1] else None, "target": s["target_percent"]}
            for s in subjects]


def teacher_analytics(teacher_id: int, subject_id: int, granularity: str = "week") -> TeacherAnalytics:
    from src.utils.errors import NotFoundError
    subjects = subject_service.list_teacher_subjects(teacher_id)
    subject = next((s for s in subjects if s["subject_id"] == subject_id), None)
    if subject is None:
        raise NotFoundError("subject not owned", user_message="That subject was not found.")
    tz = local_tz()
    sessions = _summaries(subject_id)
    sessions.sort(key=lambda s: (s["started_at"], s["session_id"]))
    roster = {r["students"]["student_id"]: r["students"]["name"] for r in enrollment_repository.rosters([subject_id])}
    att = {r["student_id"]: r for r in ar.subject_student_attendance([subject_id])}
    people = []
    for sid, name in roster.items():
        a = att.get(sid, {"attended": 0, "conducted": 0})
        if a["conducted"]:
            people.append({"student_id": sid, "name": name, "percentage": am.percentage(a["attended"], a["conducted"]), "attended": a["attended"], "conducted": a["conducted"]})
    ranked = tr.ranking(people)
    records = ar.records_for_sessions([s["session_id"] for s in sessions]) if sessions else []
    for r in records:
        r["subject_id"] = subject_id
    start_of = {s["session_id"]: s["started_at"].timestamp() for s in sessions}
    hist = _histories(records, start_of)
    n, assumed = fc.classes_in_horizon(list(start_of.values()))
    fcs = []
    for sid, name in roster.items():
        f = fc.forecast(hist.get((subject_id, sid), []), subject["target_percent"], n, assumed)
        fcs.append({"student_id": sid, "name": name, "forecast": f})
    order = {am.HIGH: 0, am.MEDIUM: 1, am.LOW: 2, am.NO_DATA: 3}
    fcs.sort(key=lambda x: (order[x["forecast"].risk], -x["forecast"].prob_below_target, x["name"].lower()))
    counted = [s["conducted"] for s in sessions]
    return TeacherAnalytics(
        subject=subject, trend=tr.trend(sessions, granularity, tz), totals=tr.status_totals(sessions),
        distribution=tr.distribution([p["percentage"] for p in people]), ranking=ranked,
        class_average=am.percentage(sum(p["attended"] for p in people), sum(p["conducted"] for p in people)) if people else None,
        highest=ranked[0] if ranked else None, lowest=ranked[-1] if ranked else None,
        participation={"sessions": len(sessions), "avg_students_counted": round(sum(counted) / len(counted), 1) if counted else 0.0,
                       "enrolled": len(roster)},
        heatmap=tr.heatmap(sessions, records, roster), time_slots=tr.weekday_hour_counts(sessions, tz), forecasts=fcs, n_future=n,
    )


# ───────────────────────── anomalies ─────────────────────────
def _anomaly_inputs(subject_ids: list[int] | None):
    sessions = ar.sessions_detail(subject_ids)
    summaries = {r["session_id"]: r for r in ar.session_summaries(None)}
    out = []
    for s in sessions:
        sm = summaries.get(s["session_id"], {})
        out.append({**s, "started_at": parse_ts(s["started_at"]), "ended_at": parse_ts(s["ended_at"]) if s.get("ended_at") else None,
                    "present": sm.get("present", 0), "late": sm.get("late", 0), "absent": sm.get("absent", 0), "conducted": sm.get("conducted", 0),
                    "stats": s.get("recognition_stats")})
    ids = [s["session_id"] for s in out]
    records = ar.records_for_sessions(ids) if ids else []
    corr_rows = ar.corrections_for_records([r["record_id"] for r in records]) if records else []
    rec = {r["record_id"]: r for r in records}
    subj = {s["session_id"]: s["subject_id"] for s in out}
    corrections = [{"correction_id": c["correction_id"], "record_id": c["record_id"], "session_id": rec[c["record_id"]]["session_id"],
                    "student_id": rec[c["record_id"]]["student_id"], "subject_id": subj.get(rec[c["record_id"]]["session_id"]),
                    "teacher_id": c["corrected_by"], "old_status": c["old_status"], "new_status": c["new_status"],
                    "created_at": parse_ts(c["created_at"]), "reverted_at": c["reverted_at"]} for c in corr_rows if c["record_id"] in rec]
    return out, records, corrections


def teacher_anomalies(teacher_id: int) -> list[an.Anomaly]:
    ids = [s["subject_id"] for s in subject_service.list_teacher_subjects(teacher_id)]
    if not ids:
        return []
    sessions, records, corrections = _anomaly_inputs(ids)
    return an.detect(sessions, records, corrections)


def admin_anomalies() -> list[an.Anomaly]:
    sessions, records, corrections = _anomaly_inputs(None)
    return an.detect(sessions, records, corrections)


# ───────────────────────── assistant helpers (all RLS-scoped, read-only) ─────────────────────────
def students_missed_last(teacher_id: int, subject_id: int, n: int) -> dict:
    """Students whose most recent `n` counted classes in the subject were ALL absences (needs at least n completed classes)."""
    subjects = subject_service.list_teacher_subjects(teacher_id)
    subject = next((s for s in subjects if s["subject_id"] == subject_id), None)
    from src.utils.errors import NotFoundError
    if subject is None:
        raise NotFoundError("subject not owned", user_message="That subject was not found.")
    sessions = [s for s in ar.sessions_detail([subject_id]) if s["status"] == "COMPLETED"]
    roster = {r["students"]["student_id"]: r["students"]["name"] for r in enrollment_repository.rosters([subject_id])}
    start_of = {s["session_id"]: parse_ts(s["started_at"]).timestamp() for s in sessions}
    records = ar.records_for_sessions(list(start_of)) if start_of else []
    for r in records:
        r["subject_id"] = subject_id
    hist = _histories(records, start_of)
    names = sorted(name for sid, name in roster.items() if len(hist.get((subject_id, sid), [])) >= n and not any(hist[(subject_id, sid)][-n:]))
    return {"subject": subject["name"], "classes": n, "completed_classes": len(sessions), "students": names}


def sessions_on(day, subject_ids: list[int] | None = None) -> list[dict]:
    """Non-cancelled session summaries that started on local date `day`, newest first."""
    tz = local_tz()
    out = []
    for s in ar.session_summaries(None):
        if s["status"] == "CANCELLED":
            continue
        if parse_ts(s["started_at"]).astimezone(tz).date() == day and (subject_ids is None or s["subject_id"] in subject_ids):
            out.append(s)
    return out


def subject_period_summary(teacher_id: int, subject_id: int, period: str, now=None) -> dict:
    from datetime import datetime, timedelta
    from src.utils.errors import NotFoundError
    subject = next((s for s in subject_service.list_teacher_subjects(teacher_id) if s["subject_id"] == subject_id), None)
    if subject is None:
        raise NotFoundError("subject not owned", user_message="That subject was not found.")
    tz = local_tz()
    today = (now or datetime.now(tz)).astimezone(tz).date()
    start = {"all": None, "this_week": today - timedelta(days=today.weekday()), "this_month": today.replace(day=1)}[period]
    sessions = [s for s in _summaries(subject_id) if start is None or s["started_at"].astimezone(tz).date() >= start]
    totals = tr.status_totals(sessions)
    attended, conducted = totals["present"] + totals["late"], totals["present"] + totals["late"] + totals["absent"]
    return {"subject": subject["name"], "period": period, "sessions": len(sessions), **totals, "percentage": am.percentage(attended, conducted) if conducted else None}
