"""Face image quality assessment (pure numpy/PIL: no model needed, fully unit-testable).

Measured on the face crop only:
  sharpness  variance of the Laplacian of a 112x112 grayscale crop (scale-normalised)
  brightness mean luminance; contrast = luminance standard deviation
  clipping   share of blown-out / crushed pixels
  size       shorter side of the detected box
  cut-off    the box touches the frame edge (part of the face is missing)
Head pose is NOT measured: the engines do not expose landmarks, so pose problems are not detected.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

CROP = 112
# Strict gate (enrolment) - tuned on the sample images in tests; override via env in settings if your cameras differ.
BLUR_MIN = 40.0          # Laplacian variance below this = blurry
DARK_MAX = 60.0          # mean luminance below this = too dark
BRIGHT_MIN = 200.0       # mean luminance above this = washed out
CONTRAST_MIN = 22.0
CLIP_MAX = 0.25          # >25% of pixels blown out/crushed
MIN_SIDE = 80            # enrolment faces must be at least this many pixels wide

MESSAGES = {
    "BLURRY": "The photo is blurry. Hold still and make sure the camera is focused.",
    "TOO_DARK": "The photo is too dark. Face a light source.",
    "TOO_BRIGHT": "The photo is overexposed. Avoid a bright light directly behind or on your face.",
    "LOW_CONTRAST": "The photo is flat or washed out. Use even, natural lighting.",
    "TOO_SMALL": "Your face is too small in the photo. Move closer to the camera.",
    "CUT_OFF": "Part of your face is outside the photo. Keep your whole face inside the frame.",
    "LOW_CONFIDENCE": "We are not confident that this is a clear face. Face the camera directly.",
}
BLOCKING = frozenset(MESSAGES)


@dataclass(frozen=True)
class QualityReport:
    score: float                                  # 0..100
    sharpness: float
    brightness: float
    contrast: float
    clipped: float
    size: int
    issues: tuple[str, ...] = field(default_factory=tuple)   # codes from MESSAGES

    @property
    def ok(self) -> bool:
        return not self.issues

    def messages(self) -> list[str]:
        return [MESSAGES[c] for c in self.issues]


def _gray(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


def laplacian_variance(gray: np.ndarray) -> float:
    g = gray.astype(float)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def _clamp01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def assess(image: np.ndarray, box: tuple[int, int, int, int], det_score: float = 1.0, *, min_side: int = MIN_SIDE) -> QualityReport:
    """image: RGB uint8 HxWx3; box: (left, top, right, bottom) in image pixels."""
    h, w = image.shape[:2]
    l, t, r, b = box
    cut = l <= 0 or t <= 0 or r >= w or b >= h
    cl, ct, cr, cb = max(0, l), max(0, t), min(w, r), min(h, b)
    if cr - cl < 4 or cb - ct < 4:
        return QualityReport(0.0, 0.0, 0.0, 0.0, 1.0, 0, ("TOO_SMALL",))
    crop = Image.fromarray(np.ascontiguousarray(image[ct:cb, cl:cr])).convert("RGB").resize((CROP, CROP), Image.BILINEAR)
    gray = _gray(np.asarray(crop, dtype=float))
    sharp, bright, contrast = laplacian_variance(gray), float(gray.mean()), float(gray.std())
    clipped = float(((gray >= 250) | (gray <= 5)).mean())
    size = int(min(r - l, b - t))

    issues = []
    if sharp < BLUR_MIN: issues.append("BLURRY")
    if bright < DARK_MAX: issues.append("TOO_DARK")
    if bright > BRIGHT_MIN: issues.append("TOO_BRIGHT")
    if contrast < CONTRAST_MIN and "TOO_DARK" not in issues and "TOO_BRIGHT" not in issues: issues.append("LOW_CONTRAST")
    if clipped > CLIP_MAX and "TOO_DARK" not in issues and "TOO_BRIGHT" not in issues: issues.append("TOO_BRIGHT" if bright >= 128 else "TOO_DARK")
    if size < min_side: issues.append("TOO_SMALL")
    if cut: issues.append("CUT_OFF")
    if det_score < 0.5: issues.append("LOW_CONFIDENCE")

    exposure = 1.0 - _clamp01(abs(bright - 120.0) / 120.0)
    score = 100.0 * (0.35 * _clamp01(sharp / (BLUR_MIN * 3)) + 0.2 * exposure + 0.15 * _clamp01(contrast / (CONTRAST_MIN * 2.5))
                     + 0.2 * _clamp01(size / (min_side * 1.5)) + 0.1 * _clamp01(det_score))
    if cut:
        score *= 0.5
    return QualityReport(round(score, 1), round(sharp, 1), round(bright, 1), round(contrast, 1), round(clipped, 3), size, tuple(dict.fromkeys(issues)))


CLASS_BLUR_MIN = BLUR_MIN / 4     # classroom faces are often soft; only truly smeared crops are rejected


def usable_in_class(report: QualityReport, min_score: float) -> bool:
    """Lenient gate for classroom photos (small, off-centre faces are normal there): only hopeless crops are rejected."""
    return report.score >= min_score and report.sharpness >= CLASS_BLUR_MIN
