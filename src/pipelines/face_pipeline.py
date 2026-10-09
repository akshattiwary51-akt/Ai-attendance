"""dlib baseline face embedding extraction (models are cached and lazily imported)."""
from __future__ import annotations

import numpy as np
import streamlit as st

from src.utils.errors import AIError
from src.utils.logging import get_logger

log = get_logger(__name__)


@st.cache_resource(show_spinner=False)
def load_dlib_models():
    try:
        import dlib
        import face_recognition_models
    except ImportError as exc:
        log.error("face_models_unavailable error=%s", exc)
        raise AIError("dlib/face_recognition_models not installed", user_message="Face recognition models are not installed on this server.") from exc

    detector = dlib.get_frontal_face_detector()
    shape_predictor = dlib.shape_predictor(face_recognition_models.pose_predictor_model_location())
    recognizer = dlib.face_recognition_model_v1(face_recognition_models.face_recognition_model_location())
    return detector, shape_predictor, recognizer


def get_face_embeddings(image_np: np.ndarray) -> list[np.ndarray]:
    """Return one 128-d embedding per detected face in an RGB uint8 image."""
    detector, shape_predictor, recognizer = load_dlib_models()
    try:
        faces = detector(image_np, 1)
        return [np.array(recognizer.compute_face_descriptor(image_np, shape_predictor(image_np, f), 1)) for f in faces]
    except RuntimeError as exc:  # dlib raises RuntimeError on unsupported image types
        log.error("face_embedding_failed error=%s", exc)
        raise AIError("dlib failed", user_message="Could not process this image. Use a standard RGB photo.") from exc
