"""Timestamp parsing/formatting in the configured display timezone."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config.settings import get_settings


def local_tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().app_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_ts(value: str) -> datetime:
    """Parse an ISO timestamp from the DB (timestamptz; a naive value is treated as UTC)."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_local(value: str | None, fmt: str = "%Y-%m-%d %I:%M %p") -> str:
    return parse_ts(value).astimezone(local_tz()).strftime(fmt) if value else "-"
