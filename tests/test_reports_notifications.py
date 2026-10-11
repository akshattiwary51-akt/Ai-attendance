"""Reports (CSV/Excel) and in-app notifications."""
import io
from types import SimpleNamespace

import pytest

from src.services import notification_service as ns, report_service as rs
from src.services.dashboard_service import make_standing


def test_csv_neutralises_formula_injection_and_keeps_unicode():
    raw = rs.to_csv([{"Student": "=HYPERLINK(\"http://evil\")", "Note": "+1", "Name": "Zoë Ñandú", "Safe": "ok", "N": 5}])
    text = raw.decode("utf-8-sig")
    assert raw.startswith(b"\xef\xbb\xbf") and "'=HYPERLINK" in text and "'+1" in text and "Zoë Ñandú" in text and ",ok," in text
    assert rs.to_csv([]) == b"\xef\xbb\xbf"


def test_xlsx_roundtrip_and_injection_guard():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(rs.to_xlsx({"Students": [{"Name": "=1+1", "Pct": 80.5}], "Empty": []})))
    ws = wb["Students"]
    assert [c.value for c in ws[1]] == ["Name", "Pct"] and ws["A2"].value == "'=1+1" and ws["B2"].value == 80.5 and wb["Empty"].max_row == 1


def _student_overview():
    low, ok, tight = make_standing(1, 3, 6, 0, 75), make_standing(2, 9, 10, 0, 75), make_standing(3, 3, 4, 0, 75)
    subs = [({"name": "<b>DSA</b>"}, low), ({"name": "OS"}, ok), ({"name": "DB"}, tight)]
    return SimpleNamespace(subjects=subs)


def test_student_notifications_are_derived_and_ordered():
    items = ns.for_student(_student_overview(), face_samples=0)
    assert [n.level for n in items] == ["HIGH", "HIGH", "WARN"]
    assert items[0].title == "Add a face sample" and items[0].page == "samples"
    assert any("Below target in <b>DSA</b>" in n.title and "attend the next" in n.body for n in items)
    assert any("No room to miss a class in DB" in n.title for n in items)
    assert not any("OS" in n.title for n in items)                                      # on-target subject is quiet
    assert ns.for_student(SimpleNamespace(subjects=[({"name": "X"}, make_standing(1, 0, 0, 0, 75))]), face_samples=2) == []


def test_teacher_and_admin_notifications():
    ov = SimpleNamespace(recent_sessions=[{"status": "OPEN"}, {"status": "COMPLETED"}], at_risk=[{"risk": "HIGH"}, {"risk": "MEDIUM"}])
    items = ns.for_teacher(ov, pending_requests=2, high_anomalies=1)
    assert [n.title for n in items][0] == "1 student at high risk" and any("2 enrolment requests" in n.title for n in items) and any("1 unfinished session" == n.title for n in items)
    assert ns.for_teacher(SimpleNamespace(recent_sessions=[], at_risk=[])) == []
    assert [n.title for n in ns.for_admin({"pending_teachers": 3}, 0)] == ["3 teacher accounts awaiting approval"]
    assert ns.for_admin({"pending_teachers": 0}) == []


def test_notification_panel_escapes_user_supplied_names(monkeypatch):
    from src.ui import notifications
    captured = []
    monkeypatch.setattr(notifications.st, "expander", lambda *a, **k: __import__("contextlib").nullcontext())
    monkeypatch.setattr(notifications.st, "columns", lambda *a, **k: [SimpleNamespace(markdown=lambda html, **kw: captured.append(html), button=lambda *a, **k: None)] * 2)
    notifications.notifications_panel(ns.for_student(_student_overview()), "k")
    assert captured and all("<b>DSA</b>" not in c for c in captured) and any("&lt;b&gt;DSA" in c for c in captured)
