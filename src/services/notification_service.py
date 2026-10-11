"""In-app notifications derived from real attendance data (pure functions: data in, list out). Nothing is stored or sent.

Email or push delivery is not implemented; these are the alerts a user sees when they open SnapClass.
"""
from __future__ import annotations

from dataclasses import dataclass

HIGH, WARN, INFO = "HIGH", "WARN", "INFO"
_ORDER = {HIGH: 0, WARN: 1, INFO: 2}


@dataclass(frozen=True)
class Notification:
    level: str
    title: str
    body: str = ""
    page: str | None = None          # navigation key the UI can offer as an action


def _sorted(items: list[Notification]) -> list[Notification]:
    return sorted(items, key=lambda n: _ORDER[n.level])


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def for_student(overview, face_samples: int | None = None) -> list[Notification]:
    out: list[Notification] = []
    if face_samples == 0:
        out.append(Notification(HIGH, "Add a face sample", "Without one you cannot be recognised in class.", "samples"))
    for sub, st in overview.subjects:
        if not st.conducted:
            continue
        if st.percentage < st.target:
            need = "the target can no longer be reached" if st.to_recover is None else f"attend the next {_plural(st.to_recover, 'class', 'classes')} in a row to recover"
            out.append(Notification(HIGH, f"Below target in {sub['name']}", f"{st.percentage:g}% against a {st.target:g}% target; {need}.", "trends"))
        elif st.can_miss == 0:
            out.append(Notification(WARN, f"No room to miss a class in {sub['name']}", f"You are at {st.percentage:g}%, right on the {st.target:g}% target.", "trends"))
    return _sorted(out)


def for_teacher(overview, pending_requests: int = 0, high_anomalies: int = 0) -> list[Notification]:
    out: list[Notification] = []
    open_sessions = [r for r in overview.recent_sessions if r["status"] == "OPEN"]
    if open_sessions:
        out.append(Notification(WARN, f"{_plural(len(open_sessions), 'unfinished session')}", "Open the attendance flow to review and save, or cancel it.", "take_attendance"))
    if pending_requests:
        out.append(Notification(WARN, f"{_plural(pending_requests, 'enrolment request')} to review", "Students are waiting for your approval.", "manage_subjects"))
    high = [r for r in overview.at_risk if r["risk"] == "HIGH"]
    if high:
        out.append(Notification(HIGH, f"{_plural(len(high), 'student')} at high risk", "They are well below a subject's attendance target.", "students"))
    if high_anomalies:
        out.append(Notification(WARN, f"{_plural(high_anomalies, 'unusual pattern')} flagged", "Review the flags in Analytics. Nothing has been changed.", "analytics"))
    return _sorted(out)


def for_admin(overview: dict, high_anomalies: int = 0) -> list[Notification]:
    out: list[Notification] = []
    if overview.get("pending_teachers"):
        out.append(Notification(WARN, f"{_plural(overview['pending_teachers'], 'teacher account')} awaiting approval", "They cannot log in until you approve them.", "overview"))
    if high_anomalies:
        out.append(Notification(WARN, f"{_plural(high_anomalies, 'unusual pattern')} flagged", "Review them under Anomalies.", "anomalies"))
    return _sorted(out)
