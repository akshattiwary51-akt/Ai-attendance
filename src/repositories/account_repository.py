"""Account provisioning: the ONLY use of the service-role key (server-side)."""
from __future__ import annotations

from src.repositories._base import call_rpc


def provision(user_id: str, role: str, name: str, email: str, *, active: bool = True, roll_number: str | None = None,
              face: list[float] | None = None, voice: list[float] | None = None, face_model: str = "dlib-resnet-128", face_quality: float | None = None) -> int:
    return int(call_rpc("provision_account", {
        "p_user_id": user_id, "p_role": role, "p_name": name, "p_email": email, "p_active": active,
        "p_roll_number": roll_number, "p_face": face, "p_voice": voice, "p_face_model": face_model, "p_face_quality": face_quality,
    }, admin=True))
