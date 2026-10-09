"""Orchestrates face / voice recognition for the UI (galleries loaded once per run)."""
from __future__ import annotations

from typing import Iterable

import numpy as np
from PIL import Image

from src.config.settings import get_settings
from src.pipelines.face_matching import RECOGNIZED, best_match
from src.repositories import student_repository
from src.services.attendance_service import Detection
from src.utils.errors import AIError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)


def _embeddings(image: Image.Image) -> list[np.ndarray]:
    from src.pipelines.face_pipeline import get_face_embeddings

    return get_face_embeddings(np.asarray(image.convert("RGB")))


def extract_single_face_embedding(image: Image.Image) -> list[float] | None:
    """Embedding of the only face in *image*, or ``None`` unless exactly one face is found."""
    found = _embeddings(image)
    return found[0].tolist() if len(found) == 1 else None


def detect_faces_in_photos(images: Iterable[Image.Image], roster: list[dict]) -> dict[int, Detection]:
    """Match every face in every photo against the *enrolled* roster only.

    A student seen in several photos yields a single Detection listing all photos.
    """
    gallery = student_repository.get_face_gallery([s["student_id"] for s in roster])
    threshold = get_settings().face_threshold
    sightings: dict[int, list[tuple[str, float]]] = {}
    for idx, image in enumerate(images, start=1):
        for embedding in _embeddings(image):
            match = best_match(embedding, gallery, threshold)
            if match.status == RECOGNIZED:
                sightings.setdefault(match.student_id, []).append((f"Photo {idx}", match.distance))
    out = {}
    for student_id, seen in sightings.items():
        photos = list(dict.fromkeys(p for p, _ in seen))  # unique, ordered
        out[student_id] = Detection(student_id, ", ".join(photos), None)
    log_event(log, "photo_attendance_processed", recognized=len(out), roster=len(roster))
    return out


def detect_speakers(audio_bytes: bytes, roster: list[dict]) -> tuple[dict[int, Detection], int]:
    """Returns (detections, number_of_roster_students_with_voice_profiles)."""
    from src.pipelines.voice_pipeline import process_bulk_audio

    gallery = student_repository.get_voice_gallery([s["student_id"] for s in roster])
    if not gallery:
        return {}, 0
    scores = process_bulk_audio(audio_bytes, gallery, get_settings().voice_threshold)
    return {sid: Detection(sid, "Voice", round(score, 3)) for sid, score in scores.items()}, len(gallery)


__all__ = ["extract_single_face_embedding", "detect_faces_in_photos", "detect_speakers", "AIError"]
