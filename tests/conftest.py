import pytest

from src.config import settings as settings_module


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for var in (
        "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY",
        "REQUIRE_TEACHER_APPROVAL", "FACE_THRESHOLD", "FACE_MARGIN", "FACE_ENGINE", "FACE_TOP_K",
        "MIN_FACE_PX", "LIVENESS_MODE", "CLASSROOM_MIN_QUALITY", "VOICE_THRESHOLD",
        "MIN_SPEECH_SECONDS", "MAX_UPLOAD_MB", "MAX_IMAGE_SIDE", "APP_BASE_URL",
        "APP_TIMEZONE", "ATTENDANCE_TARGET", "RISK_BUFFER",
    ):
        monkeypatch.delenv(var, raising=False)
    settings_module.get_settings.cache_clear()
    from src.database import client
    from src.security import principal
    client.reset_clients()
    yield
    settings_module.get_settings.cache_clear()
    client.reset_clients()
    principal.set_provider(None)


class FakeQuery:
    """Minimal PostgREST-like builder: .range(a, b).execute()."""

    def __init__(self, rows):
        self.rows, self.window, self.calls = rows, None, 0

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        from types import SimpleNamespace

        self.calls += 1
        a, b = self.window
        return SimpleNamespace(data=self.rows[a : b + 1])
