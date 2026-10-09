"""Centralised configuration (environment variables first, then Streamlit secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from src.utils.errors import ConfigurationError


def _load_project_env(env_file: Path | None = None) -> None:
    load_dotenv(env_file or Path(__file__).resolve().parents[2] / ".env", override=False)


_load_project_env()


def _read(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except FileNotFoundError:  # no secrets.toml present
        pass
    return default


def _float(name: str, default: float) -> float:
    raw = _read(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number", user_message=f"Invalid configuration value for {name}.") from exc


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str          # public key: used with the logged-in user's JWT, so RLS applies
    supabase_service_key: str       # server-side secret: ONLY for account provisioning / admin bootstrap
    require_teacher_approval: bool  # new teacher accounts stay inactive until an admin approves them
    face_threshold: float  # max Euclidean distance (dlib) to accept a face match
    voice_threshold: float  # min cosine similarity to accept a speaker match
    min_speech_seconds: float
    max_upload_mb: int
    max_image_side: int
    app_base_url: str
    app_timezone: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        supabase_url=_read("SUPABASE_URL", "") or "",
        supabase_anon_key=_read("SUPABASE_ANON_KEY", "") or "",
        supabase_service_key=_read("SUPABASE_SERVICE_ROLE_KEY") or _read("SUPABASE_KEY", "") or "",
        require_teacher_approval=(_read("REQUIRE_TEACHER_APPROVAL", "true") or "true").lower() not in ("0", "false", "no"),
        face_threshold=_float("FACE_THRESHOLD", 0.6),
        voice_threshold=_float("VOICE_THRESHOLD", 0.65),
        min_speech_seconds=_float("MIN_SPEECH_SECONDS", 0.5),
        max_upload_mb=int(_float("MAX_UPLOAD_MB", 10)),
        max_image_side=int(_float("MAX_IMAGE_SIDE", 2000)),
        app_base_url=(_read("APP_BASE_URL", "https://snapclass-main.streamlit.app") or "").rstrip("/"),
        app_timezone=_read("APP_TIMEZONE", "UTC") or "UTC",
    )


def require_supabase_settings(*, service: bool = False) -> Settings:
    """Validate the keys needed: anon (user-scoped access) and, when *service*, the service-role key."""
    s = get_settings()
    missing = [n for n, v in (("SUPABASE_URL", s.supabase_url), ("SUPABASE_ANON_KEY", s.supabase_anon_key)) if not v]
    if service and not s.supabase_service_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise ConfigurationError(
            f"missing settings: {missing}",
            user_message="The server is not configured: " + ", ".join(missing) + " must be set.",
        )
    return s
