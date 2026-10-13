"""Health checks: pure config validation, model detection and DB probes with a fake database."""
import dataclasses

import pytest

from src.config import settings
from src.repositories import _base
from src.services import health_service as hs
from src.utils.errors import DatabaseError


@pytest.fixture
def good(monkeypatch):
    for k, v in {"SUPABASE_URL": "http://x", "SUPABASE_ANON_KEY": "anon-secret", "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
                 "APP_BASE_URL": "https://app.example.com"}.items():
        monkeypatch.setenv(k, v)
    settings.get_settings.cache_clear()
    yield settings.get_settings()
    settings.get_settings.cache_clear()


def status(checks, name): return next(c.status for c in checks if c.name == name)


def test_valid_config_has_no_problems(good):
    assert not [c for c in hs.validate_config(good) if c.status == hs.FAIL]


def test_missing_and_invalid_settings_are_reported(good):
    bad = dataclasses.replace(good, supabase_url="", face_engine="magic", voice_threshold=2.0, app_timezone="Mars/Base", assistant_mode="llm", anthropic_api_key="")
    cs = hs.validate_config(bad)
    for name in ("SUPABASE_URL", "FACE_ENGINE", "VOICE_THRESHOLD", "APP_TIMEZONE", "ANTHROPIC_API_KEY"):
        assert status(cs, name) == hs.FAIL, name


def test_plain_http_base_url_is_warned(good):
    cs = hs.validate_config(dataclasses.replace(good, app_base_url="http://school.example.com"))
    assert any(c.status == hs.WARN and c.name == "APP_BASE_URL" for c in cs)


def test_no_secret_value_appears_in_any_check(good):
    text = " ".join(f"{c.name} {c.detail}" for c in hs.validate_config(good) + hs.model_status(good))
    assert "anon-secret" not in text and "service-secret" not in text


def test_onnx_missing_files_reported(good, monkeypatch, tmp_path):
    monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path))
    cs = hs.model_status(dataclasses.replace(good, face_engine="onnx"))
    c = next(c for c in cs if c.name == "Face engine (onnx)")
    assert c.status == hs.FAIL and "det_500m.onnx" in c.detail


class Q:
    def __init__(self, fail): self.fail = fail
    def select(self, *a, **k): return self
    def limit(self, n): return self
    def execute(self):
        if self.fail: raise RuntimeError("boom")
        return type("R", (), {"data": []})()


def test_database_probe_reports_missing_migration(monkeypatch):
    monkeypatch.setattr(_base, "table", lambda name: Q(fail=name == "subject_invites"))
    cs = hs.database_status()
    bad = [c for c in cs if c.status == hs.FAIL]
    assert [c.name for c in bad] == ["Table subject_invites"] and "0007" in bad[0].detail
    assert "boom" not in bad[0].detail


def test_report_overall_is_worst_status(good, monkeypatch):
    monkeypatch.setattr(_base, "table", lambda name: Q(fail=False))
    rep = hs.report()
    assert rep["version"] and set(rep["checks"]) == {"Configuration", "Models", "Database"}
    monkeypatch.setattr(_base, "table", lambda name: Q(fail=True))
    assert hs.report()["overall"] == hs.FAIL
