"""Audio quality metrics and speech segmentation on synthetic audio (no models needed)."""
import numpy as np
import pytest

from src.pipelines import voice_quality as vq

rng = np.random.default_rng(0)


def speech(sec, amp=0.2):
    t = np.arange(int(sec * vq.SR)) / vq.SR
    return amp * np.sin(2 * np.pi * 140 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)) + 0.005 * rng.normal(size=t.size)


def sil(sec, amp=0.002):
    return amp * rng.normal(size=int(sec * vq.SR))


def test_clean_recording_passes():
    q = vq.assess(np.concatenate([sil(.5), speech(3), sil(.5)]))
    assert q.ok and q.score > 85 and 2.8 < q.speech_seconds < 3.4 and q.snr_db > 25


@pytest.mark.parametrize("make, issue", [
    (lambda: np.concatenate([sil(.5), speech(1.0), sil(.5)]), "TOO_SHORT"),
    (lambda: np.concatenate([sil(.5), speech(3, 0.003), sil(.5, 1e-5)]), "TOO_QUIET"),
    (lambda: np.concatenate([sil(.5), np.clip(speech(3, 3.0), -1, 1), sil(.5)]), "CLIPPED"),
    (lambda: speech(3) + 0.1 * rng.normal(size=48000), "NOISY"),
    (lambda: sil(3), "NO_SPEECH"),
    (lambda: np.zeros(10), "NO_SPEECH"),
])
def test_defects_are_reported_with_messages(make, issue):
    q = vq.assess(make())
    assert issue in q.issues and not q.ok and q.messages()


def test_nan_audio_never_crashes():
    w = speech(3); w[100] = np.nan
    assert vq.assess(w).issues == ("NO_SPEECH",)


def test_segmentation_bridges_short_gaps_and_drops_blips():
    w = np.concatenate([sil(.5), speech(1.0), sil(.2), speech(1.0), sil(.8), speech(.2), sil(.5), speech(1.5), sil(.5)])
    spans = vq.speech_intervals(w, 0.5)
    assert len(spans) == 2                                  # 0.2 s gap bridged; the 0.2 s blip dropped; 0.8 s gap splits
    assert spans[0][1] - spans[0][0] > 2.0 * vq.SR


def test_long_runs_are_windowed():
    spans = vq.speech_intervals(np.concatenate([sil(.3), speech(13), sil(.3)]), 0.5)
    assert len(spans) >= 4 and all((e - s) <= 3.0 * vq.SR + 1 for s, e in spans)


def test_empty_and_tiny_inputs():
    assert vq.speech_intervals(np.array([]), 0.5) == [] and vq.speech_intervals(np.zeros(100), 0.5) == []
