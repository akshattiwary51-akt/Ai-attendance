"""PostgREST clients.

* ``get_client()``       - acts AS THE LOGGED-IN USER (anon key + the user's JWT) → RLS applies. Used by repositories.
* ``get_admin_client()`` - service-role key; server-side only; used solely for account provisioning.
"""
from __future__ import annotations

from threading import Lock
from typing import Any

from src.config.settings import require_supabase_settings
from src.security.principal import require_principal
from src.utils.errors import ConfigurationError


class Db:
    """Tiny facade (``table`` / ``rpc``) over postgrest-py; also what tests substitute."""

    def __init__(self, base_url: str, headers: dict[str, str]):
        try:
            from postgrest import SyncPostgrestClient
        except ImportError as exc:  # pragma: no cover
            raise ConfigurationError("postgrest missing", user_message="Database client library is not installed.") from exc
        self._client = SyncPostgrestClient(base_url, headers=headers)

    def table(self, name: str):
        return self._client.from_(name)

    def rpc(self, name: str, params: dict[str, Any]):
        return self._client.rpc(name, params)


def build_user_client(access_token: str) -> Db:
    s = require_supabase_settings()
    return Db(f"{s.supabase_url}/rest/v1", {"apikey": s.supabase_anon_key, "Authorization": f"Bearer {access_token}"})


def build_admin_client() -> Db:
    s = require_supabase_settings(service=True)
    return Db(f"{s.supabase_url}/rest/v1", {"apikey": s.supabase_service_key, "Authorization": f"Bearer {s.supabase_service_key}"})


_cache: dict[str, Db] = {}
_admin: Db | None = None
_lock = Lock()
_MAX_CACHED = 128


def reset_clients() -> None:
    global _admin
    with _lock:
        _cache.clear()
        _admin = None


def get_client() -> Db:
    """DB client for the current principal (raises AuthenticationError when nobody is logged in)."""
    token = require_principal().access_token
    with _lock:
        if token not in _cache:
            if len(_cache) >= _MAX_CACHED:
                _cache.pop(next(iter(_cache)))
            _cache[token] = build_user_client(token)
        return _cache[token]


def get_admin_client() -> Db:
    global _admin
    with _lock:
        if _admin is None:
            _admin = build_admin_client()
        return _admin
