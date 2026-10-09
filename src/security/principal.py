"""The authenticated caller. Repositories read it to build a DB client carrying the user's JWT,
so Postgres Row Level Security - not Streamlit session state - decides what each user can see."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Iterator

from src.utils.errors import AuthenticationError


@dataclass(frozen=True)
class Principal:
    user_id: str
    access_token: str = ""
    role: str | None = None            # ADMIN | TEACHER | STUDENT (None while the profile is still being loaded)
    teacher_id: int | None = None
    student_id: int | None = None

    def __repr__(self) -> str:         # never print the token
        return f"Principal(user_id={self.user_id!r}, role={self.role!r})"


_override: ContextVar[Principal | None] = ContextVar("principal_override", default=None)
_provider: Callable[[], Principal | None] | None = None


def set_provider(provider: Callable[[], Principal | None] | None) -> None:
    """Install how the *current* principal is found (the Streamlit app reads st.session_state)."""
    global _provider
    _provider = provider


def current_principal() -> Principal | None:
    return _override.get() or (_provider() if _provider else None)


def require_principal() -> Principal:
    principal = current_principal()
    if principal is None or not principal.access_token:
        raise AuthenticationError("no principal", user_message="Please log in to continue.")
    return principal


@contextmanager
def acting_as(principal: Principal) -> Iterator[Principal]:
    token = _override.set(principal)
    try:
        yield principal
    finally:
        _override.reset(token)
