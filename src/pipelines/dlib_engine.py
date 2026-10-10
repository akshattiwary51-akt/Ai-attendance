"""dlib baseline engine: HOG detector + 5/68-point shape predictor + ResNet-128 embedding."""
from __future__ import annotations

import numpy as np

from src.pipelines.face_engine import EUCLIDEAN, DetectedFace, FaceRecognitionEngine, register
from src.utils.errors import AIError
from src.utils.logging import get_logger

log = get_logger(__name__)


class DlibEngine(FaceRecognitionEngine):
    model_id = "dlib-resnet-128"
    metric = EUCLIDEAN
    default_threshold = 0.6
    default_margin = 0.05

    def __init__(self):
        try:
            import dlib
            import face_recognition_models
        except ImportError as exc:
            log.error("face_models_unavailable engine=dlib error=%s", exc)
            raise AIError("dlib/face_recognition_models not installed",
                          user_message="The dlib face model is not installed on this server.") from exc
        self._dlib = dlib
        self._detector = dlib.get_frontal_face_detector()
        self._shape = dlib.shape_predictor(face_recognition_models.pose_predictor_model_location())
        self._recognizer = dlib.face_recognition_model_v1(face_recognition_models.face_recognition_model_location())

    def detect_and_embed(self, image: np.ndarray) -> list[DetectedFace]:
        try:
            out = []
            for rect in self._detector(image, 1):
                emb = np.array(self._recognizer.compute_face_descriptor(image, self._shape(image, rect), 1), dtype=float)
                out.append(DetectedFace((rect.left(), rect.top(), rect.right(), rect.bottom()), emb))
            return out
        except RuntimeError as exc:   # dlib raises RuntimeError on unsupported image types
            log.error("face_embedding_failed engine=dlib error=%s", exc)
            raise AIError("dlib failed", user_message="Could not process this image. Use a standard RGB photo.") from exc


register("dlib", DlibEngine)
