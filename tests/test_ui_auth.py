"""Login / session / admin / student UI flows (AppTest) with a fake Supabase Auth and stubbed repositories."""
import time

import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import (
    admin_repository, attendance_repository, enrollment_repository, profile_repository, session_repository, subject_repository,
)
from src.security.auth_provider import set_auth_provider
from tests.fakes import FakeAuthProvider

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def provider():
    p = FakeAuthProvider(); set_auth_provider(p)
    yield p
    set_auth_provider(None)


def fresh(**state):
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def stub_teacher_world(monkeypatch):
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [
        {"subject_id": 1, "subject_code": "S1", "name": "DSA", "section": "A", "enrollments": [{"count": 3}]}])
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(session_repository, "find_open", lambda sid: None)


def login(at, email, pw, button="Login"):
    at.text_input[0].set_value(email); at.text_input[1].set_value(pw)
    return next(b for b in at.button if b.label == button).click().run()


def test_teacher_login_success_stores_tokens_and_shows_dashboard(provider, monkeypatch):
    uid = provider.sign_up("t@x.co", "pw-123456")
    monkeypatch.setattr(profile_repository, "get_own_profile", lambda u: {
        "role": "TEACHER", "is_active": True, "teacher_id": 5, "student_id": None, "teachers": {"name": "Ananya"}, "students": None})
    stub_teacher_world(monkeypatch)
    at = login(fresh(login_type="teacher"), "t@x.co", "pw-123456")
    assert not at.exception
    assert at.session_state["teacher_data"]["name"] == "Ananya" and at.session_state["auth"]["role"] == "TEACHER"
    assert any("Welcome, Ananya" in s.value for s in at.subheader)


def test_login_failures_show_messages_and_store_nothing(provider, monkeypatch):
    provider.sign_up("t@x.co", "pw-123456")
    monkeypatch.setattr(profile_repository, "get_own_profile", lambda u: {
        "role": "TEACHER", "is_active": False, "teacher_id": 5, "student_id": None, "teachers": {"name": "A"}, "students": None})
    at = login(fresh(login_type="teacher"), "t@x.co", "wrong-pass")
    assert any("Invalid email or password" in e.value for e in at.error)
    at = login(fresh(login_type="teacher"), "t@x.co", "pw-123456")
    assert any("pending approval" in e.value for e in at.error)
    assert "auth" not in at.session_state and "teacher_data" not in at.session_state and provider.signed_out


def test_student_cannot_enter_via_the_teacher_portal(provider, monkeypatch):
    provider.sign_up("s@x.co", "pw-123456")
    monkeypatch.setattr(profile_repository, "get_own_profile", lambda u: {
        "role": "STUDENT", "is_active": True, "teacher_id": None, "student_id": 9, "teachers": None, "students": {"name": "S"}})
    at = login(fresh(login_type="teacher"), "s@x.co", "pw-123456")
    assert any("student account" in e.value for e in at.error) and "teacher_data" not in at.session_state


AUTH = {"user_id": "u1", "access_token": "tok", "refresh_token": "refresh-u1", "expires_at": 9_999_999_999, "role": "TEACHER", "teacher_id": 5, "student_id": None}


def test_expired_token_is_refreshed_transparently(provider, monkeypatch):
    stub_teacher_world(monkeypatch)
    at = fresh(login_type="teacher", teacher_data={"teacher_id": 5, "name": "T"}, auth={**AUTH, "expires_at": int(time.time()) - 5})
    assert not at.exception and provider.refreshed == ["refresh-u1"]
    assert at.session_state["auth"]["access_token"] == "access2-u1" and at.session_state["auth"]["expires_at"] > time.time()
    assert "teacher_data" in at.session_state


def test_unrefreshable_session_is_logged_out_with_a_message(provider, monkeypatch):
    stub_teacher_world(monkeypatch)
    at = fresh(login_type="teacher", teacher_data={"teacher_id": 5, "name": "T"}, auth={**AUTH, "refresh_token": "bad-token", "expires_at": 1})
    assert not at.exception and any("session expired" in w.value.lower() for w in at.warning)
    assert "auth" not in at.session_state and "teacher_data" not in at.session_state


def test_logout_revokes_the_server_session(provider, monkeypatch):
    stub_teacher_world(monkeypatch)
    at = fresh(login_type="teacher", teacher_data={"teacher_id": 5, "name": "T"}, auth=AUTH)
    at.button(key="loginbackbtn").click().run()
    assert provider.signed_out == ["tok"] and "auth" not in at.session_state and "teacher_data" not in at.session_state


# ───── admin ─────
def admin_state():
    return dict(login_type="admin", admin_data={"name": "Root"}, auth={**AUTH, "role": "ADMIN", "teacher_id": None})


def stub_admin(monkeypatch, teachers):
    monkeypatch.setattr(admin_repository, "list_teachers", lambda: teachers)
    monkeypatch.setattr(admin_repository, "list_students", lambda: [])
    monkeypatch.setattr(admin_repository, "recent_audit", lambda limit=200: [])


def test_admin_can_approve_a_pending_teacher(provider, monkeypatch):
    calls = []
    stub_admin(monkeypatch, [{"teacher_id": 7, "name": "New T", "email": "n@x.co", "is_active": False, "created_at": "2026-01-01T00:00:00+00:00"}])
    monkeypatch.setattr(admin_repository, "set_active", lambda role, i, a: calls.append((role, i, a)))
    at = fresh(**admin_state())
    assert not at.exception and at.metric[2].value == "1"                    # 1 pending approval
    at.button(key="approve_7").click().run()
    assert calls == [("TEACHER", 7, True)]


def test_admin_dashboard_empty_states(provider, monkeypatch):
    stub_admin(monkeypatch, [])
    at = fresh(**admin_state())
    assert not at.exception and any("No teacher accounts are waiting" in s.value for s in at.success)


def test_non_admin_database_denial_is_shown_not_crashed(provider, monkeypatch):
    from src.utils.errors import AuthorizationError
    def deny(): raise AuthorizationError("rls")
    monkeypatch.setattr(admin_repository, "list_teachers", deny)
    at = fresh(**admin_state())
    assert not at.exception and any("permission" in e.value.lower() for e in at.error)


# ───── student ─────
def test_student_dashboard_shows_enrolled_subjects_and_percentage(provider, monkeypatch):
    monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda sid: [
        {"subject_id": 1, "subject_code": "DSA1", "name": "DSA", "section": "A"}])
    monkeypatch.setattr(attendance_repository, "list_for_student", lambda sid: [
        {"status": "PRESENT", "attendance_sessions": {"subject_id": 1}}, {"status": "ABSENT", "attendance_sessions": {"subject_id": 1}}])
    at = fresh(login_type="student", student_data={"student_id": 9, "name": "Hamza"}, auth={**AUTH, "role": "STUDENT", "student_id": 9, "teacher_id": None})
    assert not at.exception
    card = next(m.value for m in at.markdown if "<h3" in m.value)
    assert "50.0" in card and "DSA" in card


def test_student_registration_without_consent_or_photo_is_blocked(provider):
    at = fresh(login_type="student", student_login_type="register")
    texts = {t.label: t for t in at.text_input}
    texts["Full name"].set_value("Hamza"); texts["Email"].set_value("h@x.co")
    texts["Password (min 8 characters)"].set_value("password123"); texts["Confirm password"].set_value("password123")
    next(b for b in at.button if b.label == "Create Account").click().run()
    assert not at.exception and any("biometric" in w.value.lower() for w in at.warning)
    assert not provider.users                                                  # nothing was created
