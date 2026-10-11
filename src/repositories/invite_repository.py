"""Enrolment invites (hashed tokens only; all writes via DB functions, identity from the JWT)."""
from __future__ import annotations

from src.repositories._base import call_rpc, fetch_all, table

_COLUMNS = "invite_id, subject_id, created_at, opens_at, expires_at, max_uses, uses, require_approval, revoked_at"   # never token_hash


def create(subject_id: int, token_hash: str, ttl_minutes: int, max_uses: int, require_approval: bool, opens_in_minutes: int) -> int:
    return call_rpc("create_subject_invite", {"p_subject_id": subject_id, "p_token_hash": token_hash, "p_ttl_minutes": ttl_minutes,
                                              "p_max_uses": max_uses, "p_require_approval": require_approval, "p_opens_in_minutes": opens_in_minutes})


def revoke(invite_id: int) -> None:
    call_rpc("revoke_subject_invite", {"p_invite_id": invite_id})


def list_for_subject(subject_id: int) -> list[dict]:
    return fetch_all(lambda: table("subject_invites").select(_COLUMNS).eq("subject_id", subject_id).order("invite_id", desc=True), "invite.list")


def preview(token_hash: str) -> dict:
    return call_rpc("preview_subject_invite", {"p_token_hash": token_hash}) or {"state": "NOT_FOUND"}


def redeem(token_hash: str) -> dict:
    return call_rpc("redeem_subject_invite", {"p_token_hash": token_hash}) or {"outcome": "NOT_FOUND"}


def pending_requests(subject_id: int | None = None) -> list[dict]:
    return call_rpc("list_enrollment_requests", {"p_subject_id": subject_id}) or []


def decide(request_id: int, approve: bool) -> str:
    return call_rpc("decide_enrollment_request", {"p_request_id": request_id, "p_approve": approve})
