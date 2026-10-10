"""Active liveness: a randomly chosen *movement challenge* answered with a second photo.

WHAT THIS IS: a deterrent against casual spoofing (a photo or screenshot of the student held still in front of the camera).
The student takes a neutral photo, then a second photo after doing what the random challenge says. We check that
  - exactly one face is in each photo and both pass the quality gate,
  - both photos are the same person (embedding match under the engine's own threshold),
  - the photos are not the same image,
  - the face moved/scaled the way the challenge asked.
WHAT THIS IS NOT: it does not defeat a person who moves a photo or plays a video in response to the challenge, nor a 3-D mask.
No trained anti-spoofing model is bundled; for high-stakes use add one behind the `LivenessChecker` interface or verify enrolment in person.
Challenges are direction-free of camera mirroring (closer / back / up / down).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

import numpy as np

CHALLENGES = {
    "closer": "Move your face noticeably CLOSER to the camera",
    "back": "Move your face noticeably FARTHER from the camera",
    "up": "Raise your head so your face sits HIGHER in the frame",
    "down": "Lower your head so your face sits LOWER in the frame",
}
SCALE_CLOSER = 1.15        # box width ratio second/first
SCALE_BACK = 1 / 1.15
SHIFT_FRACTION = 0.15      # vertical centre shift as a fraction of the first box height
MIN_PIXEL_DIFF = 2.0       # mean abs grey difference (0-255) below which the "two" photos are the same picture


@dataclass(frozen=True)
class LivenessResult:
    ok: bool
    reason: str = ""            # user-safe


class LivenessChecker(Protocol):
    def check(self, first: np.ndarray, second: np.ndarray, challenge: str) -> LivenessResult: ...


def new_challenge() -> str:
    return secrets.choice(sorted(CHALLENGES))


def pixel_difference(a: np.ndarray, b: np.ndarray) -> float:
    from PIL import Image
    def small(x): return np.asarray(Image.fromarray(x).convert("L").resize((64, 64)), dtype=float)
    return float(np.abs(small(a) - small(b)).mean())


def challenge_answered(box1: tuple[int, int, int, int], box2: tuple[int, int, int, int], challenge: str) -> LivenessResult:
    if challenge not in CHALLENGES:
        return LivenessResult(False, "Unknown liveness challenge. Please start again.")
    w1, w2 = max(1, box1[2] - box1[0]), max(1, box2[2] - box2[0])
    h1 = max(1, box1[3] - box1[1])
    ratio = w2 / w1
    dy = ((box2[1] + box2[3]) - (box1[1] + box1[3])) / 2 / h1          # +ve = second face lower in the frame
    ok = {"closer": ratio >= SCALE_CLOSER, "back": ratio <= SCALE_BACK, "up": dy <= -SHIFT_FRACTION, "down": dy >= SHIFT_FRACTION}[challenge]
    return LivenessResult(True) if ok else LivenessResult(False, f"We did not see the movement asked for. Please try again: {CHALLENGES[challenge]}.")
