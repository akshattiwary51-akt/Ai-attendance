"""Expiring, revocable, usage-limited enrolment invites.

The token is a random 192-bit secret shown once; only its SHA-256 hash is stored, so the database cannot reveal a working link
and a revoked or expired token is rejected server-side. (Random-token-plus-hash rather than HMAC signing, because revocation
and use counting need server state anyway.)
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import quote

from src.config.settings import get_settings
from src.repositories import invite_repository
from src.utils.errors import ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
TTL_CHOICES = {"1 hour": 60, "1 day": 1440, "7 days": 10080, "30 days": 43200}
USE_CHOICES = (1, 10, 50, 200)


class Redeem(str, Enum):
    ENROLLED = "ENROLLED"
    ALREADY_ENROLLED = "ALREADY_ENROLLED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NOT_FOUND = "NOT_FOUND"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    USED_UP = "USED_UP"
    NOT_OPEN = "NOT_OPEN"


MESSAGES = {
    Redeem.NOT_FOUND: "This invite link is not valid.", Redeem.EXPIRED: "This invite has expired. Ask your teacher for a new one.",
    Redeem.REVOKED: "This invite was cancelled by your teacher.", Redeem.USED_UP: "This invite has already been used the maximum number of times.",
    Redeem.NOT_OPEN: "Enrolment through this invite has not opened yet. Try again later.",
}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    if not _TOKEN.match(token or ""):
        raise ValidationError("bad token", user_message="This invite link is not valid.")
    return hashlib.sha256(token.encode()).hexdigest()


def link(token: str) -> str:
    return f"{get_settings().app_base_url}/?invite={quote(token, safe='')}"


def create(subject_id: int, ttl_minutes: int, max_uses: int, require_approval: bool = False, opens_in_minutes: int = 0) -> dict:
    """Create an invite; returns {invite_id, token, url}. The token is not recoverable later."""
    token = new_token()
    invite_id = invite_repository.create(subject_id, hash_token(token), ttl_minutes, max_uses, require_approval, opens_in_minutes)
    log_event(log, "invite_created", subject_id=subject_id, invite_id=invite_id)
    return {"invite_id": invite_id, "token": token, "url": link(token)}


def state_of(invite: dict, now: datetime | None = None) -> str:
    from src.utils.timefmt import parse_ts
    now = now or datetime.now(timezone.utc)
    if invite.get("revoked_at"):
        return "REVOKED"
    if now >= parse_ts(invite["expires_at"]):
        return "EXPIRED"
    if now < parse_ts(invite["opens_at"]):
        return "NOT_OPEN"
    if invite["uses"] >= invite["max_uses"]:
        return "USED_UP"
    return "VALID"


def list_invites(subject_id: int) -> list[dict]:
    return [{**i, "state": state_of(i)} for i in invite_repository.list_for_subject(subject_id)]


def revoke(invite_id: int) -> None:
    invite_repository.revoke(invite_id)
    log_event(log, "invite_revoked", invite_id=invite_id)


def preview(token: str) -> dict:
    return invite_repository.preview(hash_token(token))


def redeem(token: str) -> tuple[Redeem, dict | None]:
    result = invite_repository.redeem(hash_token(token))
    outcome = Redeem(result["outcome"])
    if outcome in (Redeem.ENROLLED, Redeem.PENDING_APPROVAL):
        log_event(log, "invite_redeemed", outcome=outcome.value, subject_id=result.get("subject_id"))
    return outcome, ({k: result.get(k) for k in ("subject_id", "name", "section")} if "subject_id" in result else None)


def pending_requests(subject_id: int | None = None) -> list[dict]:
    return invite_repository.pending_requests(subject_id)


def decide(request_id: int, approve: bool) -> str:
    return invite_repository.decide(request_id, approve)
