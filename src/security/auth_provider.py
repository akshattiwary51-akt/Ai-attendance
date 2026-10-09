"""Supabase Auth (GoTrue) wrapper. Fresh client per call: supabase-py keeps session state inside a
client object, so sharing one across Streamlit users would mix their sessions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.config.settings import require_supabase_settings
from src.utils.errors import AppError, AuthenticationError, ConfigurationError, ValidationError
from src.utils.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class AuthSession:
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: int  # unix seconds


class AuthProvider(Protocol):
    def sign_up(self, email: str, password: str) -> str: ...
    def sign_in(self, email: str, password: str) -> AuthSession: ...
    def refresh(self, refresh_token: str) -> AuthSession: ...
    def sign_out(self, access_token: str) -> None: ...
    def delete_user(self, user_id: str) -> None: ...
    def create_confirmed_user(self, email: str, password: str) -> str: ...


def _client(service: bool = False):
    s = require_supabase_settings(service=service)
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover
        raise ConfigurationError("supabase missing", user_message="Authentication library is not installed.") from exc
    return create_client(s.supabase_url, s.supabase_service_key if service else s.supabase_anon_key)


def _translate(exc: Exception) -> AppError:
    code = (getattr(exc, "code", None) or "").lower() if isinstance(getattr(exc, "code", None), str) else ""
    message = (getattr(exc, "message", "") or "").lower()
    log.warning("auth_error type=%s code=%s", type(exc).__name__, code)
    if code in ("invalid_credentials",) or "invalid login" in message or "invalid credentials" in message:
        return AuthenticationError("bad credentials")
    if code == "email_not_confirmed" or "not confirmed" in message:
        return AuthenticationError("unconfirmed", user_message="Please confirm your email address first (check your inbox).")
    if code in ("user_already_exists", "email_exists") or "already registered" in message:
        return ValidationError("exists", user_message="An account with this email already exists.")
    if code in ("weak_password",) or "password" in message and "should" in message:
        return ValidationError("weak", user_message="That password is too weak. Use at least 8 characters.")
    if code in ("over_request_rate_limit", "over_email_send_rate_limit") or "rate limit" in message:
        return AuthenticationError("rate limited", user_message="Too many attempts. Please wait a minute and try again.")
    return AuthenticationError("auth failure", user_message="Authentication failed. Please try again.")


class SupabaseAuthProvider:
    def _guard(self, fn):
        try:
            return fn()
        except AppError:
            raise
        except Exception as exc:  # gotrue/httpx raise many types; always re-raised as a typed AppError
            raise _translate(exc) from exc

    @staticmethod
    def _session(resp) -> AuthSession:
        sess = resp.session
        if sess is None or resp.user is None:
            raise AuthenticationError("no session")
        return AuthSession(resp.user.id, sess.access_token, sess.refresh_token, int(sess.expires_at or 0))

    def sign_up(self, email: str, password: str) -> str:
        resp = self._guard(lambda: _client().auth.sign_up({"email": email, "password": password}))
        if resp.user is None:
            raise AuthenticationError("signup failed", user_message="Could not create the account.")
        return resp.user.id

    def sign_in(self, email: str, password: str) -> AuthSession:
        return self._session(self._guard(lambda: _client().auth.sign_in_with_password({"email": email, "password": password})))

    def refresh(self, refresh_token: str) -> AuthSession:
        return self._session(self._guard(lambda: _client().auth.refresh_session(refresh_token)))

    def sign_out(self, access_token: str) -> None:
        self._guard(lambda: _client(service=True).auth.admin.sign_out(access_token))

    def delete_user(self, user_id: str) -> None:
        self._guard(lambda: _client(service=True).auth.admin.delete_user(user_id))

    def create_confirmed_user(self, email: str, password: str) -> str:
        resp = self._guard(lambda: _client(service=True).auth.admin.create_user({"email": email, "password": password, "email_confirm": True}))
        return resp.user.id


_provider: AuthProvider | None = None


def get_auth_provider() -> AuthProvider:
    return _provider or SupabaseAuthProvider()


def set_auth_provider(provider: AuthProvider | None) -> None:
    global _provider
    _provider = provider
