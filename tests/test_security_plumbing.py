import os

import pytest

from src.database import client
from src.repositories import _base
from src.security import principal as pr
from src.security.principal import Principal, acting_as, current_principal, require_principal
from src.utils.errors import (
    AuthenticationError, AuthorizationError, ConflictError, DatabaseError, DuplicateError, NotFoundError, ValidationError,
)


def test_principal_repr_never_contains_the_token():
    p = Principal("u1", "SECRET-TOKEN", "TEACHER", 1)
    assert "SECRET" not in repr(p) and "SECRET" not in str(p)


def test_require_principal_without_login_or_token():
    with pytest.raises(AuthenticationError):
        require_principal()
    with acting_as(Principal("u1", "")):
        with pytest.raises(AuthenticationError):
            require_principal()


def test_acting_as_is_scoped_and_overrides_provider():
    pr.set_provider(lambda: Principal("from-provider", "t0"))
    assert current_principal().user_id == "from-provider"
    with acting_as(Principal("override", "t1")):
        assert current_principal().user_id == "override"
    assert current_principal().user_id == "from-provider"


def test_user_client_carries_the_users_jwt_and_anon_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co"); monkeypatch.setenv("SUPABASE_ANON_KEY", "ANON")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SERVICE")
    db = client.build_user_client("USER-JWT")
    headers = db._client.session.headers
    assert headers["apikey"] == "ANON" and headers["authorization"] == "Bearer USER-JWT"
    assert "SERVICE" not in str(dict(headers))
    assert str(db._client.session.base_url).rstrip("/") == "https://p.supabase.co/rest/v1"


def test_admin_client_requires_the_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co"); monkeypatch.setenv("SUPABASE_ANON_KEY", "ANON")
    from src.utils.errors import ConfigurationError
    with pytest.raises(ConfigurationError) as ei:
        client.build_admin_client()
    assert "SUPABASE_SERVICE_ROLE_KEY" in ei.value.user_message and "ANON" not in ei.value.user_message


def test_legacy_supabase_key_is_treated_as_the_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "LEGACY"); monkeypatch.setenv("SUPABASE_URL", "u"); monkeypatch.setenv("SUPABASE_ANON_KEY", "a")
    from src.config.settings import get_settings
    assert get_settings().supabase_service_key == "LEGACY"


def test_project_env_file_loads_without_overriding_process_environment(tmp_path, monkeypatch):
    from src.config.settings import _load_project_env

    env_file = tmp_path / ".env"
    env_file.write_text("SNAPCLASS_TEST_SETTING=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SNAPCLASS_TEST_SETTING", "from-process")
    _load_project_env(env_file)
    assert os.environ["SNAPCLASS_TEST_SETTING"] == "from-process"

    monkeypatch.delenv("SNAPCLASS_TEST_SETTING")
    _load_project_env(env_file)
    assert os.environ["SNAPCLASS_TEST_SETTING"] == "from-file"


def test_get_client_is_per_token_and_never_falls_back_to_service_role(monkeypatch):
    built = []
    monkeypatch.setattr(client, "build_user_client", lambda t: built.append(t) or object())
    monkeypatch.setattr(client, "build_admin_client", lambda: pytest.fail("service role must not be used for user queries"))
    with pytest.raises(AuthenticationError):
        client.get_client()
    with acting_as(Principal("a", "tok-a")):
        c1 = client.get_client(); assert client.get_client() is c1
    with acting_as(Principal("b", "tok-b")):
        assert client.get_client() is not c1
    assert built == ["tok-a", "tok-b"]


class E(Exception):
    def __init__(self, code, message=""): self.code, self.message = code, message


@pytest.mark.parametrize("code,message,expected", [
    ("23505", "", DuplicateError), ("42501", "", AuthorizationError), ("PT403", "", AuthorizationError),
    ("PT404", "session not found", NotFoundError), ("PT409", "session is not open", ConflictError),
    ("PT422", "a reason is required", ValidationError), ("23514", "", ValidationError),
    ("PGRST301", "JWSError", AuthenticationError), ("PGRST303", "JWT expired", AuthenticationError),
    ("XX000", "", DatabaseError), (None, "", DatabaseError),
])
def test_db_error_translation(code, message, expected):
    assert type(_base.translate(E(code, message), "x")) is expected


def test_db_messages_are_user_safe_sentences_and_raw_text_never_leaks():
    assert _base.translate(E("PT409", "session is not open"), "x").user_message == "Session is not open."
    leaky = _base.translate(E("XX000", 'relation "secret_table" does not exist'), "x")
    assert "secret_table" not in leaky.user_message
    assert "jwt" not in _base.translate(E("PGRST301", "JWSError detail"), "x").user_message.lower()
