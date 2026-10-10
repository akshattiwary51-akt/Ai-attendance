"""Teacher dashboard UI tabs and widget escaping."""
import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import analytics_repository as ar, enrollment_repository, session_repository, subject_repository
from src.ui import widgets
from tests.test_ui_auth import kpi

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def test_widgets_escape_and_clamp():
    assert "&lt;b&gt;" in widgets.kpi_html("<b>", "<i>x</i>", "<u>")
    assert "<i>" not in widgets.kpi_html("l", "<i>", "")
    html = widgets.progress_html(150, -5)
    assert "width:100.0%" in html and "left:0.0%" in html
    assert "sc-bad" in widgets.progress_html(50, 75) and "sc-ok" in widgets.progress_html(80, 75)


def test_standing_messages():
    from src.services.dashboard_service import make_standing
    assert "No classes" in widgets.standing_message(make_standing(1, 0, 0, 0, 75))
    assert "can miss 2 more classes" in widgets.standing_message(make_standing(1, 9, 10, 0, 75))   # 9/12 = 75%
    assert "can miss 1 more class and" in widgets.standing_message(make_standing(1, 3, 3, 0, 75))   # 3/4 = 75%
    assert "cannot afford" in widgets.standing_message(make_standing(1, 3, 4, 0, 75))
    assert "next 2 classes" in widgets.standing_message(make_standing(1, 1, 2, 0, 75))


@pytest.fixture
def teacher_app(monkeypatch):
    subs = [{"subject_id": 1, "subject_code": "S1", "name": "<b>Algo</b>", "section": "A", "target_percent": 75, "enrollments": [{"count": 2}]}]
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: subs)
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(session_repository, "find_open", lambda sid: None)
    monkeypatch.setattr(enrollment_repository, "rosters", lambda ids: [
        {"subject_id": 1, "students": {"student_id": 1, "name": "Low One"}}, {"subject_id": 1, "students": {"student_id": 2, "name": "Fine Two"}}])
    monkeypatch.setattr(ar, "subject_student_attendance", lambda ids=None: [
        {"subject_id": 1, "student_id": 1, "attended": 1, "conducted": 4, "excused": 0, "last_session_at": None},
        {"subject_id": 1, "student_id": 2, "attended": 4, "conducted": 4, "excused": 0, "last_session_at": None}])
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [])

    def build(tab):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["login_type"] = "teacher"
        at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
        at.session_state["current_teacher_tab"] = tab
        return at.run()
    return build


def test_default_tab_is_dashboard_with_kpis_and_at_risk(teacher_app):
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["login_type"] = "teacher"; at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
    at.run()
    assert not at.exception
    assert kpi(at, "Subjects") == "1" and kpi(at, "Students") == "2" and kpi(at, "Low-attendance students") == "1"
    assert any("Low One" in str(d.value.values) for d in at.dataframe)


def test_students_tab_filters(teacher_app):
    at = teacher_app("students")
    assert not at.exception and "Low One" in str(at.dataframe[0].value.values) and "Fine Two" in str(at.dataframe[0].value.values)
    at.text_input(key="student_search").set_value("fine").run()
    shown = str(at.dataframe[0].value.values)
    assert "Fine Two" in shown and "Low One" not in shown
    at.text_input(key="student_search").set_value("nobody").run()
    assert any("No students match" in m.value for m in at.markdown)


def test_settings_saves_target(teacher_app, monkeypatch):
    got = []
    monkeypatch.setattr(ar, "set_subject_target", lambda sid, t: got.append((sid, t)))
    at = teacher_app("settings")
    at.number_input(key="target_1").set_value(80.0).run()
    at.button(key="save_target_1").click().run()
    assert not at.exception and got == [(1, 80.0)]


def test_subjects_tab_details_are_escaped(teacher_app):
    at = teacher_app("manage_subjects")
    assert not at.exception
    assert not any("<b>Algo</b>" in m.value for m in at.markdown)
