"""Structured logging helpers that never emit secrets or biometric vectors."""
from __future__ import annotations

import logging
import os
from typing import Any

_SENSITIVE = ("password", "token", "secret", "key", "embedding", "hash", "vector")
_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        logging.basicConfig(
            level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        _configured = True
    return logging.getLogger(name)


def _safe(key: str, value: Any) -> Any:
    return "[redacted]" if any(s in key.lower() for s in _SENSITIVE) else value


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log ``event key=value ...`` with sensitive fields redacted."""
    rendered = " ".join(f"{k}={_safe(k, v)!r}" for k, v in sorted(fields.items()))
    logger.log(level, "%s %s", event, rendered)
