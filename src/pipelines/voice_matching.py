"""Pure speaker-matching helpers (no librosa / resemblyzer / streamlit imports)."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


def identify_speaker(embedding, candidates: Mapping[int, Sequence[float]], threshold: float) -> tuple[int | None, float]:
    """Best candidate by cosine similarity; ``(None, best_score)`` if below *threshold*."""
    best_id, best_score = None, -1.0
    for student_id, stored in candidates.items():
        if stored is None or len(stored) != len(embedding):
            continue
        score = cosine_similarity(embedding, stored)
        if score > best_score:
            best_id, best_score = student_id, score
    if best_id is None or best_score < threshold:
        return None, best_score
    return best_id, best_score


def select_segments(intervals: Iterable[Sequence[int]], sample_rate: int, min_seconds: float) -> list[tuple[int, int]]:
    """Keep only speech segments at least *min_seconds* long."""
    return [(int(s), int(e)) for s, e in intervals if (e - s) >= sample_rate * min_seconds]
