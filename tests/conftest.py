import pytest

from src.config import settings as settings_module


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for var in (
        "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY",
        "FACE_THRESHOLD", "VOICE_THRESHOLD", "APP_TIMEZONE", "MAX_UPLOAD_MB",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("REQUIRE_TEACHER_APPROVAL", raising=False)
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
