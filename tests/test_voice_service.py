"""Voice enrolment and classroom analysis with a fake backend (the algorithm is real; only the encoder is faked)."""
import numpy as np
import pytest

from src.config import settings
from src.pipelines import voice_quality as vq
from src.repositories import student_repository
from src.services import recognition_service as rs
from src.utils.errors import ValidationError

rng = np.random.default_rng(5)
VOICES = {i: rng.normal(size=256) for i in (1, 2, 3)}


def speech(sec, amp=0.2, f=140):
    t = np.arange(int(sec * vq.SR)) / vq.SR
    return amp * np.sin(2 * np.pi * f * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)) + 0.003 * rng.normal(size=t.size)


def sil(sec): return 0.002 * rng.normal(size=int(sec * vq.SR))


class Backend:
    """decode(): the 'bytes' are an index into a registry of waveforms. embed(): the dominant tone frequency picks the speaker."""
    model_id = "fake-voice"
    waves: dict = {}

    def decode(self, data): return self.waves[data]

    def embed(self, wav):
        spec = np.abs(np.fft.rfft(wav)); f = np.argmax(spec) * vq.SR / len(wav)
        who = {140: 1, 220: 2, 330: 3}[min((140, 220, 330), key=lambda x: abs(x - f))]
        return VOICES[who] + 0.01 * rng.normal(size=256)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    settings.get_settings.cache_clear()
    monkeypatch.setattr(student_repository, "get_voice_gallery",
                        lambda ids=None, model=None: {i: [VOICES[i].tolist()] for i in (ids or VOICES) if i in VOICES and model == "fake-voice"})
    yield
    settings.get_settings.cache_clear()


def run(*parts, roster=(1, 2, 3)):
    b = Backend(); b.waves = {b"x": np.concatenate(parts)}
    return rs.analyze_voice(b"x", [{"student_id": i} for i in roster], b)


def test_two_speakers_are_recognised_and_third_is_absent():
    r = run(sil(.5), speech(2, f=140), sil(.8), speech(2, f=220), sil(.5))
    assert set(r.detections) == {1, 2} and r.count("RECOGNIZED") == 2 and r.detections[1].source == "Voice"
    assert r.notes() == []


def test_unenrolled_voice_is_unknown_not_attributed():
    r = run(sil(.5), speech(2, f=330), sil(.5), roster=(1, 2))
    assert r.detections == {} and r.count("UNKNOWN") == 1 and any("did not match" in n for n in r.notes())


def test_lookalike_voices_are_ambiguous_and_not_marked(monkeypatch):
    VOICES[2] = VOICES[1] + 0.02 * rng.normal(size=256)           # students 1 and 2 sound nearly identical
    try:
        r = run(sil(.5), speech(2, f=140), sil(.5), roster=(1, 2))
    finally:
        VOICES[2] = np.random.default_rng(6).normal(size=256)
    assert r.detections == {} and r.count("AMBIGUOUS") == 1 and any("NOT marked" in n for n in r.notes())


def test_recording_drowned_in_noise_is_reported_as_noisy_not_silent():
    r = run(speech(3, f=140) + 0.12 * rng.normal(size=3 * vq.SR))
    assert r.detections == {} and r.no_speech and any("background noise" in n for n in r.notes())


def test_segment_snr_uses_the_recordings_noise_floor():
    seg = speech(2)
    assert vq.assess(seg, 0.5, 10.0, noise=vq.noise_power(np.concatenate([sil(1), seg, sil(1)]))).ok
    assert "NOISY" in vq.assess(seg, 0.5, 10.0, noise=float((seg ** 2).mean()) / 4).issues       # same speech, 6 dB SNR


def test_long_continuous_recording_is_windowed_and_each_window_matched():
    r = run(sil(.3), speech(4, f=140), speech(4, f=220), sil(.3))      # two people back to back, no pause
    assert set(r.detections) == {1, 2} and len(r.segments) >= 2


def test_silence_and_no_templates():
    assert run(sil(3)).no_speech and any("No speech" in n for n in run(sil(3)).notes())
    r = run(speech(2), roster=(9,))                                     # nobody enrolled has a voice sample
    assert r.with_voice == 0 and r.students_without_templates == [9] and r.detections == {}


def test_detect_speakers_back_compat(monkeypatch):
    b = Backend(); b.waves = {b"x": np.concatenate([sil(.5), speech(2), sil(.5)])}
    monkeypatch.setattr("src.pipelines.voice_pipeline.default_backend", lambda: b)
    det, n = rs.detect_speakers(b"x", [{"student_id": 1}, {"student_id": 2}])
    assert set(det) == {1} and n == 2


# ───────── enrolment ─────────
def test_enrolment_gate_and_sample_quality(monkeypatch):
    b = Backend(); b.waves = {b"ok": np.concatenate([sil(.5), speech(3), sil(.5)]), b"short": np.concatenate([sil(.5), speech(.8), sil(.5)])}
    s = rs.prepare_voice_sample(b"ok", b)
    assert s.model_id == "fake-voice" and s.quality > 85 and len(s.embedding) == 256
    with pytest.raises(ValidationError) as ei:
        rs.prepare_voice_sample(b"short", b)
    assert "too little speech" in ei.value.user_message


def test_add_my_voice_sample_stores_embedding_and_quality(monkeypatch):
    saved = {}
    monkeypatch.setattr(student_repository, "add_voice_sample", lambda e, m, q=None: saved.update(m=m, q=q, n=len(e)))
    monkeypatch.setattr(student_repository, "my_voice_sample_counts", lambda: {"fake-voice": 3})
    b = Backend(); b.waves = {b"ok": np.concatenate([sil(.5), speech(3), sil(.5)])}
    assert rs.add_my_voice_sample(b"ok", b) == 3 and saved["m"] == "fake-voice" and saved["q"] > 85 and saved["n"] == 256


def test_sample_count_does_not_load_the_model(monkeypatch):
    monkeypatch.setattr(student_repository, "my_voice_sample_counts", lambda: {"resemblyzer": 2})
    assert rs.my_voice_sample_count() == ("resemblyzer", 2)             # would raise AIError if it tried to import resemblyzer here
