"""UI PREVIEW ONLY - runs the real SnapClass app against invented sample data so the screens can be reviewed
without a database. Nothing here is used in production and no sample figure is ever read from Supabase.

    streamlit run scripts/ui_preview.py            # then open /?role=teacher | student | admin | home
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src.repositories import (  # noqa: E402
    admin_repository, analytics_repository as ar, attendance_repository, enrollment_repository, session_repository, student_repository, subject_repository,
)

NOW = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
NAMES = ["Aarav Mehta", "Diya Nair", "Hamza Rizvi", "Isha Kapoor", "Kabir Sethi", "Meera Joshi", "Neel Bansal", "Riya Das", "Samar Khan", "Tara Iyer"]
SUBJECTS = [
    {"subject_id": 1, "subject_code": "DSA1", "name": "Data Structures", "section": "A", "target_percent": 75, "enrollments": [{"count": 10}]},
    {"subject_id": 2, "subject_code": "DBM2", "name": "Database Systems", "section": "B", "target_percent": 75, "enrollments": [{"count": 10}]},
    {"subject_id": 3, "subject_code": "OSY3", "name": "Operating Systems", "section": "A", "target_percent": 80, "enrollments": [{"count": 10}]},
]


def _sessions():
    out, sid = [], 0
    for week in range(10, 0, -1):
        for sub in (1, 2, 3):
            if (week + sub) % 2:
                continue
            sid += 1
            start = (NOW - timedelta(days=week * 3 - sub)).isoformat()
            out.append({"session_id": sid, "subject_id": sub, "teacher_id": 1, "method": "FACE", "status": "COMPLETED", "started_at": start,
                        "present": 6 + (sid % 4), "late": 1, "absent": 3 - (sid % 3), "excused": 0, "conducted": 10})
    sid += 1
    out.append({"session_id": sid, "subject_id": 1, "teacher_id": 1, "method": "FACE", "status": "COMPLETED", "started_at": NOW.isoformat(),
                "present": 8, "late": 0, "absent": 2, "excused": 0, "conducted": 10})
    sid += 1
    out.append({"session_id": sid, "subject_id": 2, "teacher_id": 1, "method": "VOICE", "status": "OPEN", "started_at": (NOW + timedelta(hours=2)).isoformat(),
                "present": 0, "late": 0, "absent": 0, "excused": 0, "conducted": 0})
    return out


def _install() -> None:
    sessions = _sessions()
    roster = [{"student_id": i + 1, "name": n} for i, n in enumerate(NAMES)]
    subject_repository.list_for_teacher = lambda t: SUBJECTS
    session_repository.completed_session_subjects = lambda ids: [{"subject_id": s["subject_id"], "session_id": s["session_id"]} for s in sessions if s["status"] == "COMPLETED"]
    session_repository.find_open = lambda sid: next((s for s in sessions if s["subject_id"] == sid and s["status"] == "OPEN"), None)
    session_repository.list_for_teacher = lambda t: [{**s, "subjects": {"name": SUBJECTS[s["subject_id"] - 1]["name"], "subject_code": SUBJECTS[s["subject_id"] - 1]["subject_code"]}}
                                                     for s in reversed(sessions)]
    session_repository.records_for_sessions = lambda ids: [{"session_id": s["session_id"], "status": "PRESENT"} for s in sessions if s["session_id"] in ids for _ in range(s["present"])] + \
                                                         [{"session_id": s["session_id"], "status": "ABSENT"} for s in sessions if s["session_id"] in ids for _ in range(s["absent"])]
    session_repository.get = lambda sid: next(({**s, "subjects": {"name": SUBJECTS[s["subject_id"] - 1]["name"], "subject_code": SUBJECTS[s["subject_id"] - 1]["subject_code"]}} for s in sessions if s["session_id"] == sid), None)
    session_repository.records = lambda sid: [{"student_id": r["student_id"], "status": "PRESENT" if (r["student_id"] + sid) % 4 else "ABSENT", "reason": None,
                                               "source": "face", "confidence": None, "manually_corrected": False, "students": {"name": r["name"]}} for r in roster]
    session_repository.corrections = lambda sid: []
    enrollment_repository.rosters = lambda ids: [{"subject_id": s, "students": r} for s in ids for r in roster]
    enrollment_repository.subjects_of_student = lambda sid: SUBJECTS
    ar.subject_student_attendance = lambda ids=None: [{"subject_id": s, "student_id": r["student_id"], "attended": 4 + (r["student_id"] * s) % 6, "conducted": 8, "excused": 0, "last_session_at": None}
                                                       for s in (ids or [1, 2, 3]) for r in roster]
    ar.session_summaries = lambda subject_id=None: [s for s in reversed(sessions) if subject_id in (None, s["subject_id"])]
    ar.sessions_detail = lambda ids=None: []
    ar.records_for_sessions = lambda ids: []
    ar.corrections_for_records = lambda ids: []
    ar.admin_overview = lambda tz: {"teachers": 4, "pending_teachers": 2, "students": 120, "subjects": 9, "sessions_today": 3, "attended": 810, "conducted": 1000, "average_attendance": 81.0}
    admin_repository.list_teachers = lambda: [
        {"teacher_id": 7, "name": "Priya Raman", "email": "priya@example.edu", "is_active": False, "created_at": NOW.isoformat()},
        {"teacher_id": 8, "name": "Vikram Rao", "email": "vikram@example.edu", "is_active": False, "created_at": NOW.isoformat()},
        {"teacher_id": 1, "name": "Ananya Roy", "email": "ananya@example.edu", "is_active": True, "created_at": NOW.isoformat()}]
    admin_repository.list_students = lambda: [{"student_id": r["student_id"], "name": r["name"], "email": f"s{r['student_id']}@example.edu", "is_active": True} for r in roster]
    admin_repository.recent_audit = lambda limit=200: [{"created_at": NOW.isoformat(), "actor_role": "ADMIN", "actor_id": 1, "action": "teacher_approved", "entity_type": "teacher", "entity_id": 1}]
    statuses = ["PRESENT", "PRESENT", "ABSENT", "PRESENT", "LATE", "PRESENT", "ABSENT", "PRESENT"]
    attendance_repository.list_for_student = lambda sid: [{"record_id": i, "status": statuses[i % 8], "attendance_sessions": {"subject_id": 1 + i % 3, "started_at": (NOW - timedelta(days=i * 3)).isoformat()}}
                                                          for i in range(1, 17)]
    student_repository.my_face_sample_counts = lambda: {"dlib-resnet-128": 2}
    student_repository.my_voice_sample_counts = lambda: {}


def main() -> None:
    _install()
    role = st.query_params.get("role", "home")
    if st.session_state.get("_preview_role") != role:
        st.session_state.clear()
        st.session_state["_preview_role"] = role
        auth = {"user_id": "preview", "access_token": "preview", "refresh_token": "preview", "expires_at": 9_999_999_999}
        if role == "teacher":
            st.session_state.update(login_type="teacher", teacher_data={"teacher_id": 1, "name": "Ananya Roy"}, is_logged_in=True, user_role="teacher",
                                    auth={**auth, "role": "TEACHER", "teacher_id": 1, "student_id": None})
        elif role == "student":
            st.session_state.update(login_type="student", student_data={"student_id": 3, "name": "Hamza Rizvi"}, is_logged_in=True, user_role="student",
                                    auth={**auth, "role": "STUDENT", "teacher_id": None, "student_id": 3})
        elif role == "admin":
            st.session_state.update(login_type="admin", admin_data={"name": "System Admin"}, is_logged_in=True, user_role="admin",
                                    auth={**auth, "role": "ADMIN", "teacher_id": None, "student_id": None})
        elif role in ("teacher-login", "student-login", "student-register", "teacher-register", "admin-login"):
            who = role.split("-")[0]
            st.session_state.update(login_type=who, **{f"{who}_login_type": role.split("-")[1] if role.endswith("register") else "login"})
    if page := st.query_params.get("page"):
        key = {"teacher": "current_teacher_tab", "student": "current_student_page", "admin": "current_admin_page"}.get(role)
        if key:
            st.session_state[key] = page
    if st.query_params.get("review") and role == "teacher" and "attendance_review" not in st.session_state and not st.session_state.get("_review_seeded"):
        import pandas as pd
        from src.components.dialog_attendance_results import start_review
        rows = [{"Name": n, "ID": i + 1, "Source": "face" if i % 3 else "-", "Confidence": (0.9 - i * 0.02) if i % 3 else None, "Status": "✅ Present" if i % 3 else "❌ Absent"}
                for i, n in enumerate(NAMES)]
        recs = [{"student_id": r["ID"], "status": "PRESENT" if r["Status"].startswith("✅") else "ABSENT", "source": None, "confidence": r["Confidence"]} for r in rows]
        start_review(pd.DataFrame(rows), recs, 99, 1, "FACE", ["2 faces were too small to match reliably."])
        st.session_state["_review_seeded"] = True
    st.sidebar.caption("Preview with invented sample data")
    exec(compile((Path(__file__).resolve().parents[1] / "app.py").read_text(), "app.py", "exec"), {"__name__": "__main__"})


main()
