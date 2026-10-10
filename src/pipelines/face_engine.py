"""Face-recognition engine interface, shared types and the engine registry.

An engine turns an RGB image into zero or more `DetectedFace`s (box + landmarks-free summary + embedding).
Embeddings from different engines are NOT comparable, so every stored template carries `engine.model_id`
and galleries are always filtered by it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

EUCLIDEAN = "euclidean"   # smaller = more similar (dlib)
COSINE = "cosine"         # larger  = more similar (ArcFace-style)


@dataclass(frozen=True)
class DetectedFace:
    box: tuple[int, int, int, int]       # left, top, right, bottom in image pixels
    embedding: np.ndarray
    det_score: float = 1.0               # detector confidence 0..1 (1.0 when the engine does not expose one)

    @property
    def size(self) -> int:
        l, t, r, b = self.box
        return max(0, min(r - l, b - t))


class FaceRecognitionEngine(ABC):
    model_id: str            # stored with every template (face_profiles.model)
    metric: str              # EUCLIDEAN or COSINE
    default_threshold: float # accept a match when distance <= t (euclidean) or similarity >= t (cosine)
    default_margin: float    # required gap between best and second-best student, in the metric's own units

    @abstractmethod
    def detect_and_embed(self, image: np.ndarray) -> list[DetectedFace]:
        """All faces in an RGB uint8 HxWx3 image."""


_REGISTRY: dict[str, type[FaceRecognitionEngine]] = {}


def register(name: str, cls: type[FaceRecognitionEngine]) -> None:
    _REGISTRY[name] = cls


_cache: dict[str, FaceRecognitionEngine] = {}


def available_engines() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def _load_builtin() -> None:
    from src.pipelines import dlib_engine, onnx_engine   # noqa: F401  (importing registers them; idempotent)


def get_engine(name: str) -> FaceRecognitionEngine:
    """Instantiate (once) the named engine. Raises AIError with a user-safe message if it cannot load."""
    from src.utils.errors import ConfigurationError
    _load_builtin()
    if name not in _REGISTRY:
        raise ConfigurationError(f"unknown face engine {name}", user_message=f"Unknown face engine '{name}'. Available: {', '.join(sorted(_REGISTRY))}.")
    if name not in _cache:
        _cache[name] = _REGISTRY[name]()
    return _cache[name]


def reset_engine_cache() -> None:
    _cache.clear()
