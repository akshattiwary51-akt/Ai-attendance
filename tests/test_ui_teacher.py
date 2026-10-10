"""UI-level regression tests using Streamlit's AppTest (repositories stubbed)."""
import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import session_repository, subject_repository

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def subjects(n, name=lambda i: f"Subject {i}"):
    return [{"subject_id": i, "subject_code": f"S{i}", "name": name(i), "section": "A", "enrollments": [{"count": i}]} for i in range(1, n + 1)]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(session_repository, "find_open", lambda sid: None)

    def build(subs, tab="manage_subjects"):
        monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: subs)
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["login_type"] = "teacher"
        at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
        at.session_state["current_teacher_tab"] = tab
        return at.run()

    return build


def cards(at):
    return [m.value for m in at.markdown if "<h3" in m.value]


def test_all_subjects_render_not_just_the_last_one(app):
    at = app(subjects(3))
    assert not at.exception
    assert len(cards(at)) == 3
    assert len([b for b in at.button if b.label.startswith("Share Code")]) == 3   # one distinct share button each


def test_single_and_zero_subjects(app):
    assert len(cards(app(subjects(1)))) == 1
    at = app([])
    assert not cards(at) and any("No subjects found" in m.value for m in at.markdown)


def test_subject_names_are_html_escaped(app):
    at = app(subjects(1, name=lambda i: "<img src=x onerror=alert(1)>"))
    html = cards(at)[0]
    assert "<img src=x" not in html and "&lt;img" in html


def test_logout_clears_all_user_state(app):
    at = app(subjects(1), tab="take_attendance")
    at.session_state["attendance_images"] = ["leftover-photo"]
    at.button(key="loginbackbtn").click().run()
    assert "teacher_data" not in at.session_state and "attendance_images" not in at.session_state
    assert at.session_state["login_type"] == "teacher"       # returns to the teacher login screen
    assert any("Teacher login" in h.value for h in at.header)


def test_take_attendance_without_subjects_shows_warning(app):
    at = app([], tab="take_attendance")
    assert any("haven't created any subjects" in w.value for w in at.warning)


def test_database_failure_shows_friendly_error_not_traceback(app, monkeypatch):
    from src.utils.errors import DatabaseError

    def boom(t): raise DatabaseError("x")
    at = app(subjects(1))
    monkeypatch.setattr(subject_repository, "list_for_teacher", boom)
    at.run()
    assert not at.exception and any("database error" in e.value.lower() for e in at.error)


# ───── session workflow UI ─────
def test_open_session_banner_and_cancel(app, monkeypatch):
    cancelled = []
    session = {"session_id": 7, "teacher_id": 1, "subject_id": 1, "method": "FACE", "status": "OPEN"}
    monkeypatch.setattr(session_repository, "find_open", lambda sid: session)
    monkeypatch.setattr(session_repository, "cancel", lambda sid: cancelled.append(sid))
    at = app(subjects(1), tab="take_attendance")
    assert any("already open" in i.value for i in at.info)
    at.button(key="cancel_open_7").click().run()
    assert cancelled == [7] and not at.exception


def _sessions_stub(monkeypatch, status="COMPLETED"):
    sub = {"name": "DSA", "subject_code": "D1"}
    sess = {"session_id": 3, "teacher_id": 1, "subject_id": 1, "method": "FACE", "status": status, "started_at": "2026-01-01T10:00:00+00:00", "subjects": sub}
    monkeypatch.setattr(session_repository, "list_for_teacher", lambda t: [sess])
    monkeypatch.setattr(session_repository, "records_for_sessions", lambda ids: [{"session_id": 3, "status": "PRESENT"}])
    monkeypatch.setattr(session_repository, "get", lambda sid: sess)
    monkeypatch.setattr(session_repository, "records", lambda sid: [
        {"student_id": 9, "status": "ABSENT", "reason": None, "source": None, "confidence": None, "manually_corrected": False, "students": {"name": "Asha"}}])
    monkeypatch.setattr(session_repository, "corrections", lambda sid: [])


def test_records_tab_lists_sessions_and_applies_a_correction(app, monkeypatch):
    calls = []
    _sessions_stub(monkeypatch)
    monkeypatch.setattr(session_repository, "correct", lambda *a: calls.append(a) or 1)
    at = app(subjects(1), tab="attendance_records")
    assert not at.exception and len(at.dataframe) >= 2
    at.text_input[0].set_value("bus delay")
    next(b for b in at.button if b.label == "Apply correction").click().run()
    assert calls == [(3, 9, "PRESENT", "bus delay")]                 # first status option is PRESENT


def test_correction_without_reason_is_blocked_with_a_message(app, monkeypatch):
    _sessions_stub(monkeypatch)
    monkeypatch.setattr(session_repository, "correct", lambda *a: pytest.fail("must not be called"))
    at = app(subjects(1), tab="attendance_records")
    next(b for b in at.button if b.label == "Apply correction").click().run()
    assert any("reason" in w.value.lower() for w in at.warning)


def test_other_teachers_session_is_not_viewable(app, monkeypatch):
    _sessions_stub(monkeypatch)
    sess = {"session_id": 3, "teacher_id": 99, "subject_id": 1, "method": "FACE", "status": "COMPLETED", "started_at": "2026-01-01T10:00:00+00:00", "subjects": {"name": "X", "subject_code": "X"}}
    monkeypatch.setattr(session_repository, "get", lambda sid: sess)
    at = app(subjects(1), tab="attendance_records")
    assert not at.exception and any("permission" in e.value.lower() for e in at.error)


def test_empty_records_tab(app, monkeypatch):
    monkeypatch.setattr(session_repository, "list_for_teacher", lambda t: [])
    at = app(subjects(1), tab="attendance_records")
    assert any("No attendance sessions yet" in i.value for i in at.info)
