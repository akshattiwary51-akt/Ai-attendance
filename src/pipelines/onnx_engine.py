"""Modern engine: SCRFD detector + ArcFace-family recognizer (InsightFace 'buffalo' ONNX models) via onnxruntime.

Needs two files in ONNX_MODEL_DIR: a SCRFD detector (default det_500m.onnx) and a 112x112 ArcFace recognizer
(default w600k_mbf.onnx, 512-d). Only numpy + PIL + onnxruntime are used (no OpenCV).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from src.pipelines.face_engine import COSINE, DetectedFace, FaceRecognitionEngine, register
from src.utils.errors import AIError
from src.utils.logging import get_logger

log = get_logger(__name__)

# Canonical ArcFace 5-point template for a 112x112 crop (left eye, right eye, nose, left mouth, right mouth).
ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float64)
_STRIDES = (8, 16, 32)
_DET_SIZE = 640


def similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """2x3 matrix mapping src points onto dst (Umeyama least-squares similarity: rotation, uniform scale, translation)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    flip = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        flip[1, 1] = -1
    rot = u @ flip @ vt
    scale = (sig * np.diag(flip)).sum() / s.var(0).sum()
    t = mu_d - scale * rot @ mu_s
    return np.hstack([scale * rot, t[:, None]])


def align_face(image: Image.Image, landmarks: np.ndarray, size: int = 112) -> np.ndarray:
    """Warp the face onto the ArcFace template; returns an RGB (size, size, 3) uint8 array."""
    m = similarity_transform(landmarks, ARCFACE_TEMPLATE * (size / 112.0))
    inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))[:2]           # PIL wants the output->input mapping
    crop = image.transform((size, size), Image.Transform.AFFINE, tuple(inv.reshape(-1)), resample=Image.Resampling.BILINEAR)
    return np.asarray(crop)


def nms(boxes: np.ndarray, scores: np.ndarray, thresh: float) -> list[int]:
    order, keep = scores.argsort()[::-1], []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1, yy1 = np.maximum(boxes[i, 0], boxes[order[1:], 0]), np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2, yy2 = np.minimum(boxes[i, 2], boxes[order[1:], 2]), np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])   # noqa: E731
        iou = inter / (area(boxes[i]) + area(boxes[order[1:]]) - inter + 1e-9)
        order = order[1:][iou <= thresh]
    return keep


def _model_dir() -> Path:
    return Path(os.environ.get("ONNX_MODEL_DIR", "models"))


class OnnxArcFaceEngine(FaceRecognitionEngine):
    metric = COSINE
    default_threshold = 0.40     # cosine similarity; ArcFace-family models separate identities around 0.3-0.5
    default_margin = 0.05

    def __init__(self, det_file: str | None = None, rec_file: str | None = None, det_thresh: float = 0.5):
        det_file = det_file or os.environ.get("ONNX_DET_MODEL", "det_500m.onnx")
        rec_file = rec_file or os.environ.get("ONNX_REC_MODEL", "w600k_mbf.onnx")
        det_path, rec_path = _model_dir() / det_file, _model_dir() / rec_file
        missing = [str(p) for p in (det_path, rec_path) if not p.is_file()]
        if missing:
            raise AIError(f"onnx models missing: {missing}", user_message="The ONNX face models are not installed on this server (see ONNX_MODEL_DIR).")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise AIError("onnxruntime missing", user_message="onnxruntime is not installed on this server.") from exc
        opts = ort.SessionOptions(); opts.log_severity_level = 3
        providers = ["CPUExecutionProvider"]
        self._det = ort.InferenceSession(str(det_path), opts, providers=providers)
        self._rec = ort.InferenceSession(str(rec_path), opts, providers=providers)
        self.model_id = f"onnx-{Path(rec_file).stem}"
        self._det_thresh = det_thresh

    # ── detection ──
    def _detect(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        h, w = rgb.shape[:2]
        scale = _DET_SIZE / max(h, w)
        nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
        canvas = np.zeros((_DET_SIZE, _DET_SIZE, 3), np.float32)
        canvas[:nh, :nw] = np.asarray(Image.fromarray(rgb).resize((nw, nh), Image.Resampling.BILINEAR), np.float32)
        blob = ((canvas - 127.5) / 128.0).transpose(2, 0, 1)[None]
        outs = self._det.run(None, {self._det.get_inputs()[0].name: blob})
        boxes, kpss, scores = [], [], []
        for k, stride in enumerate(_STRIDES):
            sc, bb, kp = outs[k][:, 0], outs[k + 3] * stride, outs[k + 6] * stride
            n = _DET_SIZE // stride
            ys, xs = np.mgrid[:n, :n]
            centers = np.stack([xs, ys], -1).reshape(-1, 2).astype(np.float32) * stride
            centers = np.repeat(centers, 2, axis=0)                           # 2 anchors per cell
            keep = sc >= self._det_thresh
            c = centers[keep]
            boxes.append(np.stack([c[:, 0] - bb[keep, 0], c[:, 1] - bb[keep, 1], c[:, 0] + bb[keep, 2], c[:, 1] + bb[keep, 3]], 1))
            kpss.append((kp[keep].reshape(-1, 5, 2) + c[:, None, :]))
            scores.append(sc[keep])
        if not scores or sum(len(s) for s in scores) == 0:
            return np.zeros((0, 4)), np.zeros((0, 5, 2)), np.zeros(0)
        boxes, kpss, scores = np.concatenate(boxes) / scale, np.concatenate(kpss) / scale, np.concatenate(scores)
        keep = nms(boxes, scores, 0.4)
        return boxes[keep], kpss[keep], scores[keep]

    # ── embedding ──
    def _embed(self, aligned_rgb: np.ndarray) -> np.ndarray:
        blob = ((aligned_rgb.astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
        vec = self._rec.run(None, {self._rec.get_inputs()[0].name: blob})[0][0].astype(np.float64)
        return vec / (np.linalg.norm(vec) + 1e-12)

    def detect_and_embed(self, image: np.ndarray) -> list[DetectedFace]:
        try:
            pil = Image.fromarray(image)
            boxes, kpss, scores = self._detect(image)
            h, w = image.shape[:2]
            out = []
            for box, kps, sc in zip(boxes, kpss, scores):
                l, t, r, b = (int(round(v)) for v in box)
                out.append(DetectedFace((max(0, l), max(0, t), min(w, r), min(h, b)), self._embed(align_face(pil, kps)), float(sc)))
            out.sort(key=lambda f: (f.box[0], f.box[1]))
            return out
        except AIError:
            raise
        except Exception as exc:
            log.error("face_embedding_failed engine=onnx error=%s", exc)
            raise AIError("onnx failed", user_message="Could not process this image. Use a standard RGB photo.") from exc


register("onnx", OnnxArcFaceEngine)
