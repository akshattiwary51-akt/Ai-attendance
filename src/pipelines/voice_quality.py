"""Audio quality assessment and speech segmentation (pure numpy: no model, no librosa; fully unit-testable).

Energy-based voice activity detection: frames louder than the noise floor by a margin are speech. This is a simple VAD
(fine for a quiet-to-moderately-noisy room); it does not separate overlapping speakers or reject non-speech sounds."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SR = 16000
FRAME = int(SR * 0.025)
MIN_LEVEL_DBFS = -45.0     # speech RMS quieter than this = too quiet
CLIP_LEVEL, CLIP_MAX = 0.99, 0.01
MAX_SEGMENT_S, WINDOW_S = 6.0, 3.0   # longer runs (several speakers back to back) are cut into windows

MESSAGES = {
    "NO_SPEECH": "No speech was detected. Speak clearly close to the microphone.",
    "TOO_SHORT": "The recording has too little speech. Say a longer phrase (about 3 seconds).",
    "TOO_QUIET": "The recording is too quiet. Move closer to the microphone.",
    "CLIPPED": "The recording is distorted (too loud). Move back a little from the microphone.",
    "NOISY": "There is too much background noise. Record somewhere quieter.",
}


@dataclass(frozen=True)
class VoiceQuality:
    score: float
    duration: float
    speech_seconds: float
    snr_db: float
    level_dbfs: float
    clipped: float
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.issues

    def messages(self) -> list[str]:
        return [MESSAGES[c] for c in self.issues]


def _frame_db(wav: np.ndarray) -> np.ndarray:
    n = len(wav) // FRAME
    if n == 0:
        return np.array([])
    frames = wav[: n * FRAME].reshape(n, FRAME)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)


def speech_mask(wav: np.ndarray) -> np.ndarray:
    db = _frame_db(wav)
    if db.size == 0:
        return np.array([], dtype=bool)
    floor = np.percentile(db, 5)
    return db > max(floor + 8.0, db.max() - 40.0)


def speech_intervals(wav: np.ndarray, min_seconds: float, gap_seconds: float = 0.3) -> list[tuple[int, int]]:
    """[(start_sample, end_sample)] of speech runs: gaps shorter than gap_seconds are bridged, runs shorter than min_seconds dropped,
    runs longer than MAX_SEGMENT_S cut into WINDOW_S windows."""
    mask = speech_mask(wav)
    runs, start = [], None
    for i, m in enumerate(np.append(mask, False)):
        if m and start is None: start = i
        elif not m and start is not None: runs.append([start, i]); start = None
    merged: list[list[int]] = []
    gap = int(gap_seconds / 0.025)
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap: merged[-1][1] = r[1]
        else: merged.append(r)
    out: list[tuple[int, int]] = []
    for s, e in merged:
        s, e = s * FRAME, e * FRAME
        if (e - s) < SR * min_seconds:
            continue
        if (e - s) > SR * MAX_SEGMENT_S:
            step = int(SR * WINDOW_S)
            out += [(a, min(a + step, e)) for a in range(s, e, step) if min(a + step, e) - a >= SR * min_seconds]
        else:
            out.append((s, e))
    return out


def noise_power(wav: np.ndarray) -> float:
    """Background-noise power of a whole recording: mean power of its quietest 5% of frames (a recording with little silence
    therefore gives a conservative, too-high estimate rather than a too-low one)."""
    db = _frame_db(np.asarray(wav, dtype=float))
    if db.size == 0:
        return 1e-12
    power = np.sort(10 ** (db / 10))
    return float(power[: max(1, int(len(power) * 0.05))].mean())


def assess(wav: np.ndarray, min_speech_seconds: float = 2.0, min_snr_db: float = 10.0, noise: float | None = None) -> VoiceQuality:
    """`noise`: externally measured noise power (use for a short segment cut out of a longer recording, whose own frames
    contain almost no background-only audio to measure noise from)."""
    wav = np.asarray(wav, dtype=float)
    dur = len(wav) / SR
    if len(wav) < FRAME * 4 or not np.isfinite(wav).all():
        return VoiceQuality(0.0, dur, 0.0, 0.0, -120.0, 0.0, ("NO_SPEECH",))
    mask, db = speech_mask(wav), _frame_db(wav)
    speech_s = float(mask.sum() * 0.025)
    clipped = float((np.abs(wav) >= CLIP_LEVEL).mean())
    if not mask.any():
        # flat energy: either near-silence, or a constant loud sound with no speech standing out of it (noise)
        return VoiceQuality(0.0, dur, 0.0, 0.0, float(db.max()), clipped, ("NOISY",) if db.mean() > MIN_LEVEL_DBFS + 10 else ("NO_SPEECH",))
    power = 10 ** (db / 10)
    npow = noise if noise is not None else (power[~mask].mean() if (~mask).any() else 10 ** (np.percentile(db, 10) / 10))
    snr = float(10 * np.log10(power[mask].mean() / (npow + 1e-12)))
    level = float(10 * np.log10(power[mask].mean() + 1e-12))
    issues = []
    if speech_s < min_speech_seconds: issues.append("TOO_SHORT")
    if level < MIN_LEVEL_DBFS: issues.append("TOO_QUIET")
    if clipped > CLIP_MAX: issues.append("CLIPPED")
    if snr < min_snr_db: issues.append("NOISY")
    clamp = lambda x: float(max(0.0, min(1.0, x)))
    score = 100 * (0.4 * clamp(speech_s / (min_speech_seconds * 2)) + 0.4 * clamp(snr / 30) + 0.2 * clamp((level - MIN_LEVEL_DBFS) / 25))
    if clipped > CLIP_MAX: score *= 0.6
    return VoiceQuality(round(score, 1), round(dur, 2), round(speech_s, 2), round(snr, 1), round(level, 1), round(clipped, 4), tuple(issues))
