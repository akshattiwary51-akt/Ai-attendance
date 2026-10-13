"""System health for administrators: configuration problems, model availability, database reachability.

Nothing here returns a secret or a setting value that could be one: configuration issues name the variable only,
and model checks look for installed packages / files without loading (or running) any model.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from src.config.settings import Settings, get_settings
from src.repositories import _base
from src.utils.errors import AppError
from src.utils.logging import get_logger
from src.version import APP_VERSION

log = get_logger(__name__)
OK, WARN, FAIL = "ok", "warning", "problem"
_ENGINES = {"dlib", "onnx"}
_FUSION_VOICE_ONLY = {"review", "accept", "reject"}
# Tables / views a deployed database must have. A missing one usually means a migration was not applied.
_PROBES = (("teachers", "0001"), ("profiles", "0002"), ("v_subject_student_attendance", "0003"), ("face_samples", "0004"),
           ("voice_samples", "0005"), ("subject_invites", "0007"))


@dataclass(frozen=True)
class Check:
    name: str
    status: str      # OK | WARN | FAIL
    detail: str


def validate_config(s: Settings) -> list[Check]:
    """Pure: configuration problems as Checks. Never includes values of secret settings."""
    out: list[Check] = []

    def add(ok: bool, name: str, bad: str, level: str = FAIL, good: str = "Set.") -> None:
        out.append(Check(name, OK if ok else level, good if ok else bad))

    add(bool(s.supabase_url), "SUPABASE_URL", "Not set: the app cannot reach the database.")
    add(bool(s.supabase_anon_key), "SUPABASE_ANON_KEY", "Not set: users cannot sign in.")
    add(bool(s.supabase_service_key), "SUPABASE_SERVICE_ROLE_KEY", "Not set: student/teacher registration will fail.", WARN)
    add(s.face_engine in _ENGINES, "FACE_ENGINE", f"Must be one of {sorted(_ENGINES)}.", good=f"'{s.face_engine}'.")
    add(s.fusion_voice_only in _FUSION_VOICE_ONLY, "FUSION_VOICE_ONLY", f"Must be one of {sorted(_FUSION_VOICE_ONLY)}.")
    add(s.assistant_mode in ("rules", "llm"), "ASSISTANT_MODE", "Must be 'rules' or 'llm'.", good=f"'{s.assistant_mode}'.")
    if s.assistant_mode == "llm":
        add(bool(s.anthropic_api_key), "ANTHROPIC_API_KEY", "ASSISTANT_MODE=llm needs an API key; the assistant will refuse to answer.")
    add(s.liveness_mode in ("challenge", "off"), "LIVENESS_MODE", "Must be 'challenge' or 'off'.", good=f"'{s.liveness_mode}'.")
    if s.liveness_mode == "off":
        out.append(Check("Liveness", WARN, "Enrolment liveness challenge is disabled."))
    add(0 < s.voice_threshold <= 1, "VOICE_THRESHOLD", "Must be between 0 and 1.")
    add(0 <= s.voice_margin < 1, "VOICE_MARGIN", "Must be between 0 and 1.")
    add(0 <= s.fusion_voice_weight <= 1 and 0 <= s.fusion_review_below <= 1, "FUSION_*", "Weights/thresholds must be between 0 and 1.")
    add(s.max_upload_mb > 0 and s.max_audio_mb > 0 and s.max_audio_seconds > 0 and s.max_image_pixels > 0, "Upload limits", "Limits must be positive.")
    add(s.app_base_url.startswith(("http://", "https://")), "APP_BASE_URL", "Should start with http(s)://; invite links are built from it.", WARN)
    if s.app_base_url.startswith("http://") and "localhost" not in s.app_base_url and "127.0.0.1" not in s.app_base_url:
        out.append(Check("APP_BASE_URL", WARN, "Uses plain http outside localhost; invite tokens travel in the URL."))
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(s.app_timezone)
        out.append(Check("APP_TIMEZONE", OK, "Valid."))
    except Exception:  # unknown key or missing tzdata
        out.append(Check("APP_TIMEZONE", FAIL, "Not a valid IANA time zone name."))
    return out


def _has(*modules: str) -> bool:
    try:
        return all(find_spec(m) is not None for m in modules)
    except (ImportError, ValueError):
        return False


def model_status(s: Settings) -> list[Check]:
    """Whether the packages / files each model needs are present. Does not load or run a model."""
    out: list[Check] = []
    if s.face_engine == "dlib":
        ok = _has("face_recognition", "dlib")
        out.append(Check("Face engine (dlib)", OK if ok else FAIL, "Packages installed." if ok else "face_recognition / dlib are not installed."))
    elif s.face_engine == "onnx":
        d = Path(os.environ.get("ONNX_MODEL_DIR", "models"))
        files = (os.environ.get("ONNX_DET_MODEL", "det_500m.onnx"), os.environ.get("ONNX_REC_MODEL", "w600k_mbf.onnx"))
        missing = [f for f in files if not (d / f).is_file()]
        ok = _has("onnxruntime") and not missing
        out.append(Check("Face engine (onnx)", OK if ok else FAIL,
                         "Runtime and model files found." if ok else
                         ("onnxruntime is not installed. " if not _has("onnxruntime") else "") + (f"Missing model files: {', '.join(missing)}." if missing else "")))
    ok = _has("resemblyzer", "librosa")
    out.append(Check("Voice model (Resemblyzer)", OK if ok else WARN,
                     "Packages installed." if ok else "resemblyzer / librosa not installed: voice attendance is unavailable."))
    return out


def database_status() -> list[Check]:
    """Probe each expected table as the calling admin (RLS applies); reports latency and missing migrations."""
    out: list[Check] = []
    for name, migration in _PROBES:
        started = time.monotonic()
        try:
            _base.execute(_base.table(name).select("*", count="exact").limit(0), f"health.{name}")
            out.append(Check(f"Table {name}", OK, f"Reachable ({(time.monotonic() - started) * 1000:.0f} ms)."))
        except AppError as exc:
            log.warning("health_probe_failed table=%s type=%s", name, type(exc).__name__)
            out.append(Check(f"Table {name}", FAIL, f"Not reachable. Was migration {migration} applied?"))
    return out


def report() -> dict:
    s = get_settings()
    checks = {"Configuration": validate_config(s), "Models": model_status(s), "Database": database_status()}
    worst = FAIL if any(c.status == FAIL for v in checks.values() for c in v) else (
        WARN if any(c.status == WARN for v in checks.values() for c in v) else OK)
    return {"version": APP_VERSION, "overall": worst, "checks": checks}
