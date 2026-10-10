"""Assistant chat panel (AppTest)."""
import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import analytics_repository as ar, attendance_repository, enrollment_repository, session_repository, subject_repository
from src.security.auth_provider import set_auth_provider
from tests.fakes import FakeAuthProvider
from tests.test_ui_auth import AUTH

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def student_app(monkeypatch):
    monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda sid: [
        {"subject_id": 1, "subject_code": "DSA1", "name": "DSA", "section": "A", "target_percent": 75}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [{"subject_id": 1, "student_id": 9, "attended": 9, "conducted": 10, "excused": 0, "last_session_at": None}])
    monkeypatch.setattr(attendance_repository, "list_for_student", lambda sid: [
        {"record_id": i, "status": "PRESENT", "attendance_sessions": {"subject_id": 1, "started_at": f"2026-03-{i + 1:02d}T10:00:00+00:00"}} for i in range(1, 10)])
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in dict(login_type="student", student_data={"student_id": 9, "name": "Hamza"}, auth={**AUTH, "role": "STUDENT", "student_id": 9, "teacher_id": None}).items():
        at.session_state[k] = v
    return at.run()


@pytest.fixture(autouse=True)
def provider():
    p = FakeAuthProvider(); set_auth_provider(p)
    yield p
    set_auth_provider(None)


def test_student_can_ask_and_gets_an_answer(monkeypatch):
    at = student_app(monkeypatch)
    assert not at.exception, at.exception
    at.chat_input[0].set_value("Can I miss 2 more DSA classes?").run()
    assert not at.exception, at.exception
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert "Yes" in at.chat_message[1].markdown[0].value and "DSA" in at.chat_message[1].markdown[0].value


def test_bad_input_shows_a_friendly_message_and_history_clears_on_logout(monkeypatch):
    at = student_app(monkeypatch)
    at.chat_input[0].set_value("what's the weather").run()
    assert "I can help with attendance" in at.chat_message[1].markdown[0].value
    at.button(key="loginbackbtn").click().run()
    assert "assistant_history" not in at.session_state


def test_teacher_assistant_tab(monkeypatch):
    subs = [{"subject_id": 1, "subject_code": "S1", "name": "Algo", "section": "A", "target_percent": 75, "enrollments": [{"count": 2}]}]
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: subs)
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(enrollment_repository, "rosters", lambda ids: [{"subject_id": 1, "students": {"student_id": 1, "name": "Low One"}}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [{"subject_id": 1, "student_id": 1, "attended": 1, "conducted": 4, "excused": 0, "last_session_at": None}])
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["login_type"] = "teacher"; at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
    at.session_state["current_teacher_tab"] = "assistant"
    at.session_state["auth"] = {**AUTH, "role": "TEACHER", "teacher_id": 1, "student_id": None}
    at.run()
    assert not at.exception, at.exception
    at.chat_input[0].set_value("Which students are below 75%?").run()
    assert not at.exception and "Low One" in at.chat_message[1].markdown[0].value
