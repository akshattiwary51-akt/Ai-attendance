"""Registration and login on top of Supabase Auth (credentials) + the profiles/RLS model (roles)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from src.config.settings import get_settings
from src.repositories import account_repository, profile_repository
from src.security.auth_provider import AuthSession, get_auth_provider
from src.security.principal import Principal, acting_as
from src.utils.errors import AppError, AuthenticationError, DuplicateError, ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_BYTES = 72
REFRESH_MARGIN_SECONDS = 60


@dataclass(frozen=True)
class Registration:
    pending_approval: bool = False


def _validate_credentials(email: str, password: str, confirm: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValidationError("bad email", user_message="Please enter a valid email address.")
    if password != confirm:
        raise ValidationError("mismatch", user_message="Passwords don't match.")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValidationError("short", user_message=f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValidationError("long", user_message=f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return email


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name", user_message="Please enter your name.")
    if len(name) > 100:
        raise ValidationError("name long", user_message="Name is too long.")
    return name


def _create_account(email: str, password: str, role: str, name: str, **provision) -> int:
    """Create the auth user, then the app rows. If provisioning fails the auth user is removed (no orphans)."""
    provider = get_auth_provider()
    user_id = provider.sign_up(email, password)
    try:
        entity_id = account_repository.provision(user_id, role, name, email, **provision)
    except AppError as exc:
        _cleanup_user(provider, user_id)
        if isinstance(exc, DuplicateError):
            raise ValidationError("duplicate", user_message="An account with this email or roll number already exists.") from exc
        raise
    log_event(log, "account_registered", role=role, entity_id=entity_id)
    return entity_id


def _cleanup_user(provider, user_id: str) -> None:
    try:
        provider.delete_user(user_id)
    except AppError as exc:  # best effort: report loudly, never mask the original error
        log.error("orphan_auth_user_cleanup_failed user_id=%s detail=%s", user_id, type(exc).__name__)


def register_teacher(email: str, name: str, password: str, confirm: str) -> Registration:
    email, name = _validate_credentials(email, password, confirm), _clean_name(name)
    needs_approval = get_settings().require_teacher_approval
    _create_account(email, password, "TEACHER", name, active=not needs_approval)
    return Registration(pending_approval=needs_approval)


def register_student(email: str, name: str, password: str, confirm: str, roll_number: str | None,
                     face_embedding: list[float] | None, voice_embedding: list[float] | None, consent: bool) -> Registration:
    email, name = _validate_credentials(email, password, confirm), _clean_name(name)
    if not consent:
        raise ValidationError("consent", user_message="Please accept the biometric data notice to register.")
    if not face_embedding:
        raise ValidationError("face", user_message="A clear face photo is required so attendance can recognise you.")
    roll = (roll_number or "").strip() or None
    if roll and len(roll) > 40:
        raise ValidationError("roll", user_message="Roll number is too long.")
    _create_account(email, password, "STUDENT", name, roll_number=roll, face=face_embedding, voice=voice_embedding)
    return Registration()


def create_admin(email: str, password: str) -> int:
    """Bootstrap an administrator (CLI only: ``python scripts/create_admin.py``). Email is pre-confirmed."""
    email = _validate_credentials(email, password, password)
    provider = get_auth_provider()
    user_id = provider.create_confirmed_user(email, password)
    try:
        account_repository.provision(user_id, "ADMIN", "Administrator", email)
    except AppError:
        _cleanup_user(provider, user_id)
        raise
    log_event(log, "admin_created", user_id=user_id)
    return 0


def login(email: str, password: str, expected_role: str) -> dict:
    """Authenticate, verify the account's role/status through RLS, and return the session payload."""
    email = (email or "").strip().lower()
    if not email or not password:
        raise AuthenticationError("empty credentials")
    provider = get_auth_provider()
    session = provider.sign_in(email, password)
    try:
        with acting_as(Principal(user_id=session.user_id, access_token=session.access_token)):
            profile = profile_repository.get_own_profile(session.user_id)
        if profile is None:
            raise AuthenticationError("no profile", user_message="This account isn't set up yet. Please contact your administrator.")
        if not profile["is_active"]:
            raise AuthenticationError("inactive", user_message="Your account is pending approval or has been deactivated. Please contact your administrator.")
        if profile["role"] != expected_role:
            raise AuthenticationError("wrong portal", user_message=f"This is a {profile['role'].lower()} account. Please use the {profile['role'].lower()} portal.")
    except AppError:
        _sign_out_quietly(provider, session.access_token)
        log_event(log, "login_rejected", user_id=session.user_id, expected=expected_role)
        raise
    name = ((profile.get("teachers") or profile.get("students") or {}).get("name")) or "Admin"
    log_event(log, "login_ok", user_id=session.user_id, role=profile["role"])
    return {
        "auth": {"user_id": session.user_id, "access_token": session.access_token, "refresh_token": session.refresh_token,
                 "expires_at": session.expires_at, "role": profile["role"], "teacher_id": profile["teacher_id"], "student_id": profile["student_id"]},
        "user": {"teacher_id": profile["teacher_id"], "student_id": profile["student_id"], "name": name, "email": email},
    }


def needs_refresh(expires_at: int, now: float | None = None) -> bool:
    return (now if now is not None else time.time()) >= expires_at - REFRESH_MARGIN_SECONDS


def refresh(auth: dict) -> dict:
    """New token pair merged into *auth*; raises AuthenticationError if the refresh token is no longer valid."""
    session: AuthSession = get_auth_provider().refresh(auth["refresh_token"])
    return {**auth, "access_token": session.access_token, "refresh_token": session.refresh_token, "expires_at": session.expires_at}


def logout(access_token: str | None) -> None:
    if access_token:
        _sign_out_quietly(get_auth_provider(), access_token)


def _sign_out_quietly(provider, access_token: str) -> None:
    try:
        provider.sign_out(access_token)
    except AppError as exc:
        log.warning("sign_out_failed detail=%s", type(exc).__name__)
