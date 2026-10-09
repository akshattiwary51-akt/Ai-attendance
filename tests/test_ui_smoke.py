"""App must boot and degrade gracefully with no database configured (was an import-time crash)."""
from streamlit.testing.v1 import AppTest

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def run(**state):
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_home_boots_without_any_configuration():
    at = run()
    assert not at.exception
    assert {b.label for b in at.button} >= {"Student Portal", "Teacher Portal"}


def test_teacher_login_with_missing_config_shows_friendly_error():
    at = run(login_type="teacher")
    at.text_input[0].set_value("someone@x.co"); at.text_input[1].set_value("password123")
    next(b for b in at.button if b.label == "Login").click().run()
    assert not at.exception
    assert any("not configured" in e.value.lower() or "failed" in e.value.lower() for e in at.error)


def test_teacher_registration_validation_messages_are_shown():
    at = run(login_type="teacher", teacher_login_type="register")
    at.text_input[0].set_value("N"); at.text_input[1].set_value("not-an-email")
    at.text_input[2].set_value("password123"); at.text_input[3].set_value("password123")
    next(b for b in at.button if b.label == "Register now").click().run()
    assert not at.exception and any("valid email" in w.value for w in at.warning)


def test_student_portal_shows_email_login_not_face_login():
    at = run(login_type="student")
    assert not at.exception and any("Student login" in h.value for h in at.header)
    assert not at.get("camera_input")                                         # face is no longer a login credential
    assert [t.label for t in at.text_input] == ["Email", "Password"]


def test_student_registration_form_has_consent_and_privacy_notice():
    at = run(login_type="student", student_login_type="register")
    assert not at.exception
    assert any("Biometric data notice" in i.value for i in at.info)
    assert any("consent" in c.label.lower() for c in at.checkbox)


def test_admin_portal_is_reachable_from_home_and_shows_login():
    at = run()
    at.button(key="admin_portal").click().run()
    assert at.session_state["login_type"] == "admin" and any("Administrator login" in h.value for h in at.header)
