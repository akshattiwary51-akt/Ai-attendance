"""Analytics UI (AppTest with stubbed repositories) and chart builders."""
from datetime import datetime, timedelta, timezone

import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import (
    admin_repository, analytics_repository as ar, attendance_repository, enrollment_repository, session_repository, subject_repository,
)
from src.security.auth_provider import set_auth_provider
from src.ui import charts
from tests.fakes import FakeAuthProvider
from tests.test_ui_auth import AUTH, admin_state, kpi

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")
T0 = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)


def iso(d): return (T0 + timedelta(days=d)).isoformat()


def test_chart_builders_handle_empty_and_normal_input():
    assert charts.trend_line([]) is None and charts.status_bars([]) is None and charts.heatmap([]) is None and charts.time_slot_heatmap([]) is None
    assert charts.comparison_bars([{"subject": "A", "percentage": None, "target": 75}]) is None
    rows = [{"period": T0.date(), "percentage": 80.0, "present": 4, "late": 1, "absent": 1, "excused": 0}]
    assert charts.trend_line(rows, 75).to_dict() and charts.status_bars(rows).to_dict()
    assert charts.distribution_bars([{"label": "0-50%", "count": 1}]).to_dict()
    assert charts.heatmap([{"student": "A", "session": "#1", "order": 0, "value": None}]).to_dict()
    assert charts.comparison_bars([{"subject": "A", "percentage": 60, "target": 75}]).to_dict()


@pytest.fixture
def teacher_app(monkeypatch):
    subs = [{"subject_id": 1, "subject_code": "S1", "name": "Algo", "section": "A", "target_percent": 75, "enrollments": [{"count": 2}]}]
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: subs)
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(session_repository, "find_open", lambda sid: None)
    monkeypatch.setattr(enrollment_repository, "rosters", lambda ids: [
        {"subject_id": 1, "students": {"student_id": 1, "name": "Low One"}}, {"subject_id": 1, "students": {"student_id": 2, "name": "Fine Two"}}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [
        {"subject_id": 1, "student_id": 1, "attended": 2, "conducted": 8, "excused": 0, "last_session_at": None},
        {"subject_id": 1, "student_id": 2, "attended": 8, "conducted": 8, "excused": 0, "last_session_at": None}])
    summ = [{"session_id": i, "subject_id": 1, "started_at": iso(i * 7), "status": "COMPLETED", "method": "FACE", "present": 1, "late": 0, "absent": 1,
             "excused": 0, "conducted": 2} for i in range(1, 9)]
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: list(reversed(summ)))
    monkeypatch.setattr(ar, "records_for_sessions", lambda ids: [{"record_id": i * 2 + k, "session_id": i, "student_id": k + 1,
                                                                  "status": ("PRESENT" if k == 1 or i <= 2 else "ABSENT")} for i in range(1, 9) for k in (0, 1)])
    monkeypatch.setattr(ar, "sessions_detail", lambda ids=None: [{"session_id": s["session_id"], "subject_id": 1, "teacher_id": 1, "method": "FACE", "status": "COMPLETED",
                                                                  "started_at": s["started_at"], "ended_at": iso(s["session_id"] * 7 + 0.03), "recognition_stats": {"faces": 10, "unknown": 6}}
                                                                 for s in summ])
    monkeypatch.setattr(ar, "corrections_for_records", lambda ids: [])

    def build(tab="analytics"):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["login_type"] = "teacher"; at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
        at.session_state["current_teacher_tab"] = tab
        return at.run()
    return build


def test_teacher_analytics_tab_renders_kpis_forecast_and_anomalies(teacher_app):
    at = teacher_app()
    assert not at.exception, at.exception
    assert kpi(at, "Class average") == "62.5%" and kpi(at, "Highest") == "100%" and kpi(at, "Lowest") == "25%" and kpi(at, "Sessions") == "8"
    dfs = [str(d.value.values) for d in at.dataframe]
    assert any("Low One" in d and "High risk" in d for d in dfs)                       # forecast table
    assert any("Recognition Failures" in d for d in dfs)                               # anomaly table: 6 of 10 unknown, repeatedly
    assert any("flags for you to review" in c.value for c in at.caption)


def test_granularity_switch_and_missing_data(teacher_app, monkeypatch):
    at = teacher_app()
    at.radio(key="analytics_gran").set_value("Monthly").run()
    assert not at.exception
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [])
    monkeypatch.setattr(ar, "sessions_detail", lambda ids=None: [])
    at = teacher_app()
    assert not at.exception and any("No completed sessions yet" in m.value for m in at.markdown)


def test_student_dashboard_shows_forecast_with_reasons(monkeypatch):
    p = FakeAuthProvider(); set_auth_provider(p)
    try:
        monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda sid: [
            {"subject_id": 1, "subject_code": "DSA1", "name": "DSA", "section": "A", "target_percent": 75}])
        statuses = ["PRESENT", "PRESENT", "PRESENT", "ABSENT", "ABSENT", "ABSENT"]
        monkeypatch.setattr(attendance_repository, "list_for_student", lambda sid: [
            {"record_id": i, "status": s, "attendance_sessions": {"subject_id": 1, "started_at": iso(i * 7)}} for i, s in enumerate(statuses, 1)])
        monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [
            {"subject_id": 1, "student_id": 9, "attended": 3, "conducted": 6, "excused": 0, "last_session_at": None}])
        at = AppTest.from_file(APP, default_timeout=30)
        for k, v in dict(login_type="student", student_data={"student_id": 9, "name": "Hamza"}, auth={**AUTH, "role": "STUDENT", "student_id": 9, "teacher_id": None}).items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, at.exception
        assert any("Trends and forecast" in h.value for h in at.header)
        ex = next(e for e in at.expander if e.label.startswith("DSA"))
        assert "High risk" in ex.label and "chance of ending below 75%" in ex.label
        body = " ".join(m.value for m in ex.markdown)
        assert "3 classes missed in a row" in body and "Expected attendance" in body
    finally:
        set_auth_provider(None)


def test_admin_anomalies_tab(monkeypatch):
    p = FakeAuthProvider(); set_auth_provider(p)
    try:
        monkeypatch.setattr(admin_repository, "list_teachers", lambda: []); monkeypatch.setattr(admin_repository, "list_students", lambda: [])
        monkeypatch.setattr(admin_repository, "recent_audit", lambda limit=200: [])
        monkeypatch.setattr(ar, "admin_overview", lambda tz: {"teachers": 0, "pending_teachers": 0, "students": 0, "subjects": 0, "sessions_today": 0,
                                                              "attended": 0, "conducted": 0, "average_attendance": None})
        monkeypatch.setattr(ar, "sessions_detail", lambda ids=None: [])
        monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [])
        at = AppTest.from_file(APP, default_timeout=30)
        for k, v in admin_state().items():
            at.session_state[k] = v
        at.run()
        assert not at.exception and any("No unusual patterns detected across the system" in s.value for s in at.success)
    finally:
        set_auth_provider(None)
