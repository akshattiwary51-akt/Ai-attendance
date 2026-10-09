"""Pure face-matching logic (no dlib / streamlit imports, fully unit-testable)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

RECOGNIZED = "RECOGNIZED"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FaceMatch:
    student_id: int | None
    distance: float
    status: str


def _as_matrix(stored: Any) -> np.ndarray:
    """Accept one embedding or a list of embeddings per student -> (n, d) matrix."""
    arr = np.asarray(stored, dtype=float)
    return arr.reshape(1, -1) if arr.ndim == 1 else arr


def best_match(embedding: Any, gallery: Mapping[int, Any], threshold: float) -> FaceMatch:
    """Nearest enrolled student by Euclidean distance; UNKNOWN if beyond *threshold*.

    The closest identity is never assigned just because it is closest: it must
    also be within the threshold. Supports multiple stored embeddings/student.
    """
    query = np.asarray(embedding, dtype=float)
    best_id: int | None = None
    best_dist = float("inf")
    for student_id, stored in gallery.items():
        matrix = _as_matrix(stored)
        if matrix.shape[1] != query.shape[0]:
            continue  # incompatible embedding size; skip rather than crash
        dist = float(np.linalg.norm(matrix - query, axis=1).min())
        if dist < best_dist:
            best_id, best_dist = student_id, dist
    if best_id is None or best_dist > threshold:
        return FaceMatch(None, best_dist, UNKNOWN)
    return FaceMatch(best_id, best_dist, RECOGNIZED)
