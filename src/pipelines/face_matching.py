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


# ───────────────────────── metric-aware matching (Phase 5) ─────────────────────────
AMBIGUOUS = "AMBIGUOUS"          # two different students are almost equally close: never guess


@dataclass(frozen=True)
class MatchPolicy:
    metric: str            # "euclidean" | "cosine"
    threshold: float       # euclidean: distance <= t accepts; cosine: similarity >= t accepts
    margin: float = 0.0    # required gap between the best and second-best *student* (same units as the metric)
    top_k: int = 1         # aggregate a student's score over their k best samples (1 = best sample; 2+ = mean of top k)


@dataclass(frozen=True)
class MatchResult:
    status: str                    # RECOGNIZED | UNKNOWN | AMBIGUOUS
    student_id: int | None         # set only when RECOGNIZED
    score: float                   # normalised 0..1, higher is better, comparable across engines
    raw: float                     # distance or similarity of the best candidate (engine units)
    runner_up_id: int | None = None
    candidate_id: int | None = None   # nearest student even when UNKNOWN/AMBIGUOUS (for review UIs only)


def _student_raw(query: np.ndarray, stored: Any, policy: MatchPolicy) -> float | None:
    """One student's raw score: min distance (euclidean) or max similarity (cosine), over their samples."""
    m = _as_matrix(stored)
    if m.shape[1] != query.shape[0]:
        return None
    if policy.metric == "euclidean":
        vals = np.sort(np.linalg.norm(m - query, axis=1))
    else:
        mn = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)
        vals = np.sort(mn @ (query / (np.linalg.norm(query) + 1e-12)))[::-1]
    k = max(1, min(policy.top_k, len(vals)))
    return float(vals[:k].mean())


def _to_score(raw: float, policy: MatchPolicy) -> float:
    """Normalise to 0..1 so confidence is comparable: euclidean 0 -> 1.0 and threshold -> 0.5; cosine similarity as-is."""
    if policy.metric == "euclidean":
        return float(max(0.0, min(1.0, 1.0 - raw / (2.0 * policy.threshold)))) if policy.threshold > 0 else 0.0
    return float(max(0.0, min(1.0, raw)))


def match_face(embedding: Any, gallery: Mapping[int, Any], policy: MatchPolicy) -> MatchResult:
    """Identify a face against enrolled students.

    UNKNOWN  - nobody is within the threshold (or the gallery is empty).
    AMBIGUOUS - the best student passes the threshold but a different student is within `margin` of them.
    RECOGNIZED - best student passes the threshold and is clearly ahead of everyone else.
    """
    query = np.asarray(embedding, dtype=float)
    better_low = policy.metric == "euclidean"
    scored: list[tuple[float, int]] = []
    for sid, stored in gallery.items():
        raw = _student_raw(query, stored, policy)
        if raw is not None and np.isfinite(raw):
            scored.append((raw, sid))
    if not scored:
        return MatchResult(UNKNOWN, None, 0.0, float("inf") if better_low else float("-inf"))
    scored.sort(key=lambda p: p[0], reverse=not better_low)
    best_raw, best_id = scored[0]
    runner = scored[1] if len(scored) > 1 else None
    accepted = best_raw <= policy.threshold if better_low else best_raw >= policy.threshold
    score = _to_score(best_raw, policy)
    runner_id = runner[1] if runner else None
    if not accepted:
        return MatchResult(UNKNOWN, None, score, best_raw, runner_id, best_id)
    if runner is not None:
        gap = (runner[0] - best_raw) if better_low else (best_raw - runner[0])
        if gap < policy.margin:
            return MatchResult(AMBIGUOUS, None, score, best_raw, runner_id, best_id)
    return MatchResult(RECOGNIZED, best_id, score, best_raw, runner_id, best_id)
