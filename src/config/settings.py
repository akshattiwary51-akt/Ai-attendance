"""Centralised configuration (environment variables first, then Streamlit secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from src.utils.errors import ConfigurationError


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
    voice_threshold: float  # min cosine similarity to accept a speaker match
    min_speech_seconds: float
    voice_margin: float             # required cosine gap between best and second-best student
    voice_enrol_seconds: float      # minimum speech for an enrolment recording
    voice_min_snr_db: float         # minimum signal-to-noise ratio (dB) for enrolment / classroom segments
    max_upload_mb: int
    max_image_side: int
    app_base_url: str
    app_timezone: str
    attendance_target: float        # default % target for new subjects
    risk_buffer: float              # points above target still treated as medium risk
    face_engine: str                # "dlib" (baseline) or "onnx" (SCRFD + ArcFace)
    face_threshold_override: float | None   # FACE_THRESHOLD; None = use the engine's own default
    face_margin_override: float | None      # FACE_MARGIN: required gap to the runner-up student
    face_top_k: int                 # samples averaged per student when matching (1 = best sample)
    min_face_px: int                # faces smaller than this (shorter side, pixels) are reported as too small
    fusion_voice_weight: float      # how much a voice match counts relative to a face match (0..1)
    fusion_review_below: float      # a single-modality match below this confidence is flagged for review
    fusion_voice_only: str          # voice-only match in a combined session: "review" (mark + flag) | "accept" | "reject"
    assistant_mode: str             # "rules" (no external service) or "llm" (Anthropic API, opt-in)
    assistant_model: str
    anthropic_api_key: str
    assistant_rate_per_hour: int
    liveness_mode: str              # "challenge" (random movement challenge at enrolment) or "off"
    classroom_min_quality: float    # classroom faces scoring below this (0-100) are not auto-marked


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        supabase_url=_read("SUPABASE_URL", "") or "",
        supabase_anon_key=_read("SUPABASE_ANON_KEY", "") or "",
        supabase_service_key=_read("SUPABASE_SERVICE_ROLE_KEY") or _read("SUPABASE_KEY", "") or "",
        require_teacher_approval=(_read("REQUIRE_TEACHER_APPROVAL", "true") or "true").lower() not in ("0", "false", "no"),
        face_threshold_override=(_float("FACE_THRESHOLD", 0.0) or None),
        face_margin_override=(_float("FACE_MARGIN", -1.0) if _read("FACE_MARGIN") is not None else None),
        face_engine=(_read("FACE_ENGINE", "dlib") or "dlib").lower(),
        face_top_k=int(_float("FACE_TOP_K", 1)),
        min_face_px=int(_float("MIN_FACE_PX", 40)),
        fusion_voice_weight=min(1.0, max(0.0, _float("FUSION_VOICE_WEIGHT", 0.6))),
        fusion_review_below=_float("FUSION_REVIEW_BELOW", 0.6),
        fusion_voice_only=(_read("FUSION_VOICE_ONLY", "review") or "review").lower(),
        assistant_mode=(_read("ASSISTANT_MODE", "rules") or "rules").lower(),
        assistant_model=_read("ASSISTANT_MODEL", "claude-sonnet-5-5") or "claude-sonnet-5-5",
        anthropic_api_key=_read("ANTHROPIC_API_KEY", "") or "",
        assistant_rate_per_hour=int(_float("ASSISTANT_RATE_PER_HOUR", 30)),
        liveness_mode=(_read("LIVENESS_MODE", "challenge") or "challenge").lower(),
        classroom_min_quality=_float("CLASSROOM_MIN_QUALITY", 35.0),
        voice_threshold=_float("VOICE_THRESHOLD", 0.65),
        min_speech_seconds=_float("MIN_SPEECH_SECONDS", 0.5),
        voice_margin=_float("VOICE_MARGIN", 0.05),
        voice_enrol_seconds=_float("VOICE_ENROL_SECONDS", 2.0),
        voice_min_snr_db=_float("VOICE_MIN_SNR_DB", 10.0),
        max_upload_mb=int(_float("MAX_UPLOAD_MB", 10)),
        max_image_side=int(_float("MAX_IMAGE_SIDE", 2000)),
        app_base_url=(_read("APP_BASE_URL", "https://snapclass-main.streamlit.app") or "").rstrip("/"),
        app_timezone=_read("APP_TIMEZONE", "UTC") or "UTC",
        attendance_target=_float("ATTENDANCE_TARGET", 75.0),
        risk_buffer=_float("RISK_BUFFER", 5.0),
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
