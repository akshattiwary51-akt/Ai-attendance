"""Shared query execution, DB-error translation and pagination."""
from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator, Sequence

from src.database.client import get_admin_client, get_client
from src.utils.errors import (
    AuthenticationError, AuthorizationError, ConfigurationError, ConflictError, DatabaseError, DuplicateError,
    NotFoundError, ValidationError,
)
from src.utils.logging import get_logger

log = get_logger(__name__)
PAGE_SIZE = 1000  # PostgREST silently truncates results above its max-rows setting


def table(name: str):
    return get_client().table(name)


def _sentence(message: str) -> str | None:
    """DB functions raise PT4xx errors with user-safe sentences (see 0001_init.sql)."""
    message = (message or "").strip()
    return (message[0].upper() + message[1:] + ("" if message.endswith(".") else ".")) if message else None


def translate(exc: Exception, action: str) -> Exception:
    """Map a driver exception to a typed AppError (never exposes raw driver text)."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", "") or ""
    log.error("db_error action=%s code=%s type=%s", action, code, type(exc).__name__)
    if action == "rpc.provision_account" and code in (401, "401"):
        return ConfigurationError(
            "Supabase rejected the service-role credential",
            user_message="Supabase rejected the server credential. Check SUPABASE_SERVICE_ROLE_KEY in your .env file.",
        )
    if isinstance(code, str) and code.startswith("PGRST30"):   # PGRST301/303: JWT invalid / expired
        return AuthenticationError(f"{action}: jwt rejected", user_message="Your session expired. Please log in again.")
    if code == "23505":
        return DuplicateError(f"{action}: unique violation")
    if code in ("23514", "23502", "23503", "22P02"):
        return ValidationError(f"{action}: constraint {code}", user_message="Some of the submitted data is invalid.")
    if code in ("PT403", "42501"):   # 42501 = RLS violation / insufficient privilege
        return AuthorizationError(f"{action}: forbidden")
    if code == "PT404":
        return NotFoundError(f"{action}: not found", user_message=_sentence(message))
    if code == "PT409":
        return ConflictError(f"{action}: conflict", user_message=_sentence(message))
    if code == "PT422":
        return ValidationError(f"{action}: invalid", user_message=_sentence(message))
    return DatabaseError(f"{action} failed")


def execute(builder, action: str) -> list[dict[str, Any]]:
    """Run a query builder and return its rows."""
    try:
        return builder.execute().data or []
    except Exception as exc:  # driver raises postgrest.APIError / httpx errors; always re-raised typed
        raise translate(exc, action) from exc


def call_rpc(name: str, params: dict[str, Any], *, admin: bool = False) -> Any:
    """Call a Postgres function as the logged-in user (or, for provisioning only, as the service role)."""
    try:
        return (get_admin_client() if admin else get_client()).rpc(name, params).execute().data
    except Exception as exc:
        raise translate(exc, f"rpc.{name}") from exc


def fetch_all(make_query: Callable[[], Any], action: str, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Fetch every row by paging; *make_query* must return a fresh builder each call."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = execute(make_query().range(start, start + page_size - 1), action)
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def chunked(items: Sequence[Any] | Iterable[Any], size: int = 200) -> Iterator[list[Any]]:
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]
