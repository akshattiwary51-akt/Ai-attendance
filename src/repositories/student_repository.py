from __future__ import annotations

from typing import Any, Iterable

from src.repositories._base import call_rpc, chunked, fetch_all, table


def _active_profiles(profile_table: str, student_ids: Iterable[int] | None, model: str | None = None) -> list[dict]:
    action = f"student.{profile_table}"

    def base():
        q = table(profile_table).select("student_id, embedding").eq("is_active", True).order("profile_id")
        return q.eq("model", model) if model else q
    if student_ids is None:
        return fetch_all(base, action)
    rows: list[dict] = []
    for ids in chunked(student_ids):
        rows += fetch_all(lambda ids=ids: base().in_("student_id", ids), action)
    return rows


def get_face_gallery(student_ids: Iterable[int] | None = None, model: str | None = None) -> dict[int, list[Any]]:
    """{student_id: [embedding, ...]} - active face samples of ONE model (templates from different models are not comparable).
    RLS: a teacher only receives students enrolled in their subjects."""
    gallery: dict[int, list[Any]] = {}
    for row in _active_profiles("face_profiles", student_ids, model):
        gallery.setdefault(row["student_id"], []).append(row["embedding"])
    return gallery


def get_voice_gallery(student_ids: Iterable[int] | None = None, model: str | None = None) -> dict[int, list[Any]]:
    """{student_id: [embedding, ...]} - active voice samples of ONE model."""
    gallery: dict[int, list[Any]] = {}
    for row in _active_profiles("voice_profiles", student_ids, model):
        gallery.setdefault(row["student_id"], []).append(row["embedding"])
    return gallery


def add_voice_sample(embedding: list[float], model: str, quality: float | None = None) -> int:
    return int(call_rpc("add_voice_sample", {"p_embedding": embedding, "p_model": model, "p_quality": quality}))


def remove_voice_samples(model: str) -> int:
    return int(call_rpc("remove_voice_samples", {"p_model": model}))


def my_voice_sample_counts() -> dict[str, int]:
    rows = call_rpc("my_voice_sample_counts", {}) or []
    return {r["model"]: int(r["samples"]) for r in rows}


def add_face_sample(embedding: list[float], model: str, quality: float | None = None) -> int:
    return int(call_rpc("add_face_sample", {"p_embedding": embedding, "p_model": model, "p_quality": quality}))


def remove_face_samples(model: str) -> int:
    return int(call_rpc("remove_face_samples", {"p_model": model}))


def my_face_sample_counts() -> dict[str, int]:
    rows = call_rpc("my_face_sample_counts", {}) or []
    return {r["model"]: int(r["samples"]) for r in rows}
