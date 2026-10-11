"""Redesign guarantees: accessible tokens, non-colour-only status, role shell, guarded save/confirm flows."""
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.repositories import (
    admin_repository, analytics_repository as ar, attendance_repository, enrollment_repository, session_repository, subject_repository,
)
from src.security.auth_provider import set_auth_provider
from src.ui import theme, widgets
from tests.fakes import FakeAuthProvider
from tests.test_ui_auth import AUTH, admin_state, stub_admin

APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def _lum(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4  # noqa: E731
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


@pytest.mark.parametrize("tokens", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_text_and_status_colours_meet_wcag_aa(tokens):
    pairs = [("text", "bg"), ("text", "surface"), ("muted", "bg"), ("muted", "surface"), ("primary", "surface"), ("on-primary", "primary"),
             ("ok", "ok-bg"), ("warn", "warn-bg"), ("bad", "bad-bg"), ("info", "info-bg"), ("neutral", "neutral-bg")]
    for fg, bg in pairs:
        assert contrast(tokens[fg], tokens[bg]) >= 4.5, (fg, bg)


def test_hero_and_auth_panel_white_text_is_readable_on_both_gradient_ends():
    assert contrast("#FFFFFF", "#4F46E5") >= 4.5 and contrast("#FFFFFF", "#7C3AED") >= 4.5


def test_brief_palette_is_the_light_theme_base():
    assert (theme.LIGHT["primary"], theme.LIGHT["violet"], theme.LIGHT["accent"], theme.LIGHT["bg"], theme.LIGHT["surface"],
            theme.LIGHT["text"], theme.LIGHT["border"]) == ("#4F46E5", "#7C3AED", "#14B8A6", "#F8FAFC", "#FFFFFF", "#0F172A", "#E2E8F0")


def test_stylesheet_defines_both_themes_with_variables_only_for_custom_colours():
    css = theme.stylesheet("dark")
    assert "--sc-bg:#0B1120" in css and "prefers-reduced-motion" in css and ":focus-visible" in css
    assert "--sc-bg:#F8FAFC" in theme.stylesheet("light")


def test_status_is_never_colour_only():
    for status in ("PRESENT", "LATE", "ABSENT", "EXCUSED", "OPEN", "COMPLETED"):
        html = widgets.status_badge_html(status)
        assert "sc-glyph" in html and status.title() in html
        assert not any(ord(c) > 0x2000 and c not in "✓✕–" for c in widgets.status_text(status)), status   # no emoji in table text
    assert widgets.plain_status("✅ Present") == "Present" and widgets.plain_status("❌ Absent") == "Absent"


def test_stepper_marks_progress_for_assistive_tech(monkeypatch):
    captured = []
    monkeypatch.setattr(widgets.st, "markdown", lambda html, **k: captured.append(html))
    widgets.stepper(["A", "B", "C"], 2)
    html = captured[0]
    assert html.count('aria-current="step"') == 1 and html.count("sc-done") == 1 and "Done" in html and "In progress" in html and "Next" in html


def test_page_header_escapes(monkeypatch):
    captured = []
    monkeypatch.setattr(widgets.st, "markdown", lambda html, **k: captured.append(html))
    widgets.page_header("<script>x</script>", "<b>d</b>", ("<i>c</i>",))
    assert "<script>" not in captured[0] and "&lt;script&gt;" in captured[0] and "<b>d</b>" not in captured[0]


# ───── shell ─────
def run(**state):
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_signed_out_screens_have_no_navigation_but_a_back_button():
    at = run(login_type="teacher")
    assert not at.exception and not [b for b in at.sidebar.button] and any(b.key == "loginbackbtn" for b in at.button)


@pytest.fixture
def provider():
    p = FakeAuthProvider(); set_auth_provider(p)
    yield p
    set_auth_provider(None)


def test_each_role_gets_its_own_navigation(provider, monkeypatch):
    stub_admin(monkeypatch, [])
    admin = run(**admin_state())
    assert {b.key for b in admin.sidebar.button} >= {"nav_overview", "nav_users", "nav_anomalies", "nav_audit", "loginbackbtn"}
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [])
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [])
    teacher = run(login_type="teacher", teacher_data={"teacher_id": 1, "name": "T"})
    keys = {b.key for b in teacher.sidebar.button}
    assert {"nav_cta", "nav_dashboard", "nav_manage_subjects", "nav_attendance_records", "nav_analytics", "loginbackbtn"} <= keys
    student = run(login_type="student", student_data={"student_id": 9, "name": "S"}, auth={**AUTH, "role": "STUDENT", "student_id": 9, "teacher_id": None})
    assert {"nav_overview", "nav_history", "nav_trends", "nav_samples", "nav_assistant"} <= {b.key for b in student.sidebar.button}
    assert "nav_users" not in {b.key for b in student.sidebar.button}               # no admin navigation for a student


def test_nav_click_switches_page_and_marks_it_active(provider, monkeypatch):
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [])
    monkeypatch.setattr(ar, "session_summaries", lambda subject_id=None: [])
    at = run(login_type="teacher", teacher_data={"teacher_id": 1, "name": "T"})
    at.sidebar.button(key="nav_manage_subjects").click().run()
    assert at.session_state["current_teacher_tab"] == "manage_subjects" and not at.exception
    assert at.sidebar.button(key="nav_manage_subjects").proto.type == "primary" and at.sidebar.button(key="nav_dashboard").proto.type == "tertiary"


# ───── guided attendance flow: review, save, discard ─────
SESSION = {"session_id": 7, "teacher_id": 1, "subject_id": 1, "method": "FACE", "status": "OPEN"}


@pytest.fixture
def review_app(monkeypatch):
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [
        {"subject_id": 1, "subject_code": "S1", "name": "DSA", "section": "A", "enrollments": [{"count": 2}]}])
    monkeypatch.setattr(session_repository, "completed_session_subjects", lambda ids: [])
    monkeypatch.setattr(session_repository, "find_open", lambda sid: SESSION)
    calls = {"complete": [], "cancel": []}
    monkeypatch.setattr(session_repository, "complete", lambda sid, recs: calls["complete"].append((sid, recs)) or len(recs))
    monkeypatch.setattr(session_repository, "cancel", lambda sid: calls["cancel"].append(sid))
    monkeypatch.setattr(session_repository, "get", lambda sid: SESSION)
    rows = [{"Name": "Asha", "ID": 1, "Source": "face", "Confidence": 0.91, "Status": "✅ Present"},
            {"Name": "Ben", "ID": 2, "Source": "-", "Confidence": None, "Status": "❌ Absent"}]
    records = [{"student_id": 1, "status": "PRESENT", "source": "face", "confidence": 0.91}, {"student_id": 2, "status": "ABSENT", "source": None, "confidence": None}]

    def build(**extra):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["login_type"] = "teacher"; at.session_state["teacher_data"] = {"teacher_id": 1, "name": "T"}
        at.session_state["current_teacher_tab"] = "take_attendance"
        at.session_state["attendance_review"] = {"df": pd.DataFrame(rows), "records": records, "session_id": 7, "subject_id": 1, "kind": "FACE", "notes": ["1 face too small"]}
        for k, v in extra.items():
            at.session_state[k] = v
        return at.run()
    return build, calls, records


def test_review_step_shows_real_results_and_explains_the_save(review_app):
    build, _, _ = review_app
    at = build()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "1 present" in html and "1 absent" in html and "aria-current" in html
    assert any("1 face too small" in w.value for w in at.warning)
    table = at.dataframe[0].value
    assert "Present" in set(table["Status"].str.replace("✓ ", "")) and "ID" not in table.columns and "Confidence" in table.columns   # a real score exists, so it is shown
    assert any("Saving records 1 student" in m.value for m in at.markdown)


def test_confirm_saves_once_with_the_original_records_and_clears_state(review_app):
    build, calls, records = review_app
    at = build()
    at.button(key="review_confirm").click().run()
    assert calls["complete"] == [(7, records)] and not at.exception
    assert "attendance_review" not in at.session_state and at.session_state["attendance_images"] == []
    assert any("Attendance saved: 1 present or late, 1 absent" in s.value for s in at.success)


def test_second_click_while_saving_is_ignored(review_app):
    build, calls, _ = review_app
    at = build(attendance_saving=7)                                             # a save for this session is already in flight
    assert at.button(key="review_confirm").disabled and at.button(key="review_discard").disabled
    assert calls["complete"] == []


def test_discard_needs_a_confirmation_step(review_app):
    build, calls, _ = review_app
    at = build()
    at.button(key="review_discard").click().run()
    assert calls["cancel"] == [] and "attendance_review" in at.session_state     # nothing happened yet; the dialog asks first


def test_confidence_column_is_hidden_when_no_pipeline_score_exists(review_app):
    from src.components.dialog_attendance_results import review_table
    df = pd.DataFrame([{"Name": "A", "ID": 1, "Source": "-", "Confidence": None, "Status": "❌ Absent"}])
    assert "Confidence" not in review_table(df).columns


# ───── records, corrections, admin ─────
def test_reopen_and_undo_are_confirmed_before_any_write(provider, monkeypatch):
    sub = {"name": "DSA", "subject_code": "D1"}
    sess = {"session_id": 3, "teacher_id": 1, "subject_id": 1, "method": "FACE", "status": "COMPLETED", "started_at": "2026-01-01T10:00:00+00:00", "subjects": sub}
    monkeypatch.setattr(subject_repository, "list_for_teacher", lambda t: [])
    monkeypatch.setattr(session_repository, "list_for_teacher", lambda t: [sess])
    monkeypatch.setattr(session_repository, "records_for_sessions", lambda ids: [{"session_id": 3, "status": "PRESENT"}])
    monkeypatch.setattr(session_repository, "get", lambda sid: sess)
    monkeypatch.setattr(session_repository, "records", lambda sid: [
        {"student_id": 9, "status": "ABSENT", "reason": None, "source": None, "confidence": None, "manually_corrected": False, "students": {"name": "Asha"}}])
    monkeypatch.setattr(session_repository, "corrections", lambda sid: [
        {"correction_id": 5, "record_id": 1, "old_status": "PRESENT", "new_status": "ABSENT", "reason": "r", "created_at": "2026-01-01T11:00:00+00:00", "reverted_at": None,
         "attendance_records": {"students": {"name": "Asha"}}}])
    done = {"reopen": [], "undo": []}
    monkeypatch.setattr(session_repository, "reopen", lambda sid: done["reopen"].append(sid))
    monkeypatch.setattr(session_repository, "undo_correction", lambda cid: done["undo"].append(cid))
    at = run(login_type="teacher", teacher_data={"teacher_id": 1, "name": "T"}, current_teacher_tab="attendance_records")
    assert not at.exception
    at.button(key="reopen_3").click().run()
    assert done["reopen"] == [] and not at.exception                              # the dialog asks first
    at = run(login_type="teacher", teacher_data={"teacher_id": 1, "name": "T"}, current_teacher_tab="attendance_records")
    at.button(key="undo_3").click().run()
    assert done["undo"] == []
    assert done["undo"] == [] and not at.exception      # (the dialog's confirm button is exercised in the browser check; AppTest reruns the whole script)


def test_admin_deactivation_is_confirmed_and_users_are_searchable(provider, monkeypatch):
    calls = []
    stub_admin(monkeypatch, [{"teacher_id": 7, "name": "Pri Raman", "email": "p@x.co", "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"}])
    monkeypatch.setattr(admin_repository, "set_active", lambda role, i, a: calls.append((role, i, a)))
    at = run(**{**admin_state(), "current_admin_page": "users"})
    assert not at.exception
    at.button(key="toggle_TEACHER").click().run()
    assert calls == []                                                           # the confirmation dialog comes first
    at = run(**{**admin_state(), "current_admin_page": "users"})
    at.text_input(key="q_TEACHER").set_value("nobody").run()
    assert any("No accounts match" in m.value for m in at.markdown)


def test_student_history_filters_and_only_shows_own_rows(provider, monkeypatch):
    monkeypatch.setattr(enrollment_repository, "subjects_of_student", lambda sid: [
        {"subject_id": 1, "subject_code": "D1", "name": "DSA", "section": "A", "target_percent": 75}])
    monkeypatch.setattr(attendance_repository, "list_for_student", lambda sid: [
        {"record_id": 1, "status": "PRESENT", "attendance_sessions": {"subject_id": 1, "started_at": "2026-03-01T10:00:00+00:00"}},
        {"record_id": 2, "status": "ABSENT", "attendance_sessions": {"subject_id": 1, "started_at": "2026-03-02T10:00:00+00:00"}}])
    at = run(login_type="student", current_student_page="history", student_data={"student_id": 9, "name": "S"},
             auth={**AUTH, "role": "STUDENT", "student_id": 9, "teacher_id": None})
    assert not at.exception and len(at.dataframe[0].value) == 2
    at.selectbox(key="hist_status").set_value("Absent").run()
    assert len(at.dataframe[0].value) == 1 and "Absent" in at.dataframe[0].value["Status"].iloc[0]
