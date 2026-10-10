"""Multimodal fusion rules (pure logic) plus the combined flow end to end with fake engines."""
import numpy as np
import pytest

from src.config import settings
from src.pipelines.face_matching import AMBIGUOUS, RECOGNIZED, UNKNOWN
from src.services import fusion_service as fs
from src.services.attendance_service import ABSENT, PRESENT, Detection
from src.services.recognition_service import FaceOutcome, PhotoAnalysis, VoiceAnalysis

ROSTER = [{"student_id": i, "name": f"S{i}"} for i in range(1, 7)]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for k in ("FUSION_VOICE_WEIGHT", "FUSION_REVIEW_BELOW", "FUSION_VOICE_ONLY"):
        monkeypatch.delenv(k, raising=False)
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def face(dets, faces=()):
    return PhotoAnalysis(detections={i: Detection(i, "Photo 1", c) for i, c in dets.items()}, faces=list(faces))


def voice(dets):
    return VoiceAnalysis(detections={i: Detection(i, "Voice", c) for i, c in dets.items()})


def test_noisy_or_properties():
    assert fs.noisy_or(0, 0) == 0 and fs.noisy_or(1, 0.3) == 1
    assert fs.noisy_or(0.7, 0.6) > 0.7 and fs.noisy_or(0.7, 0.6) == fs.noisy_or(0.6, 0.7)


def test_every_rule():
    f = face({1: 0.9, 2: 0.9, 3: 0.4}, [FaceOutcome(1, AMBIGUOUS, None, 0.55, 5, (0, 0, 1, 1))])
    v = voice({1: 0.8, 4: 0.9, 5: 0.7})
    r = fs.fuse(ROSTER, f, v).decisions
    assert (r[1].status, r[1].source, r[1].needs_review) == (PRESENT, "Face+Voice", False)
    assert r[1].confidence == round(fs.noisy_or(0.9, 0.6 * 0.8), 3) and r[1].confidence > 0.9          # agreement raises confidence
    assert (r[2].source, r[2].needs_review, r[2].confidence) == ("Face", False, 0.9)                    # silent but seen
    assert (r[3].source, r[3].needs_review) == ("Face", True)                                           # weak face only -> review
    assert (r[4].status, r[4].source, r[4].needs_review) == (PRESENT, "Voice", True)                    # heard, not seen -> review
    assert (r[5].source, r[5].needs_review) == ("Voice resolves face", True)                            # voice settles an ambiguous face
    assert r[6].status == ABSENT and r[6].confidence is None and not r[6].needs_review


def test_voice_only_policy(monkeypatch):
    f, v = face({1: 0.9}), voice({2: 0.9})
    monkeypatch.setenv("FUSION_VOICE_ONLY", "reject"); settings.get_settings.cache_clear()
    res = fs.fuse(ROSTER, f, v)
    assert res.decisions[2].status == ABSENT and any("left absent" in n for n in res.notes)
    monkeypatch.setenv("FUSION_VOICE_ONLY", "accept"); settings.get_settings.cache_clear()
    d = fs.fuse(ROSTER, f, v).decisions[2]
    assert d.status == PRESENT and not d.needs_review                                                  # strong voice accepted unflagged
    d = fs.fuse(ROSTER, f, voice({2: 0.5})).decisions[2]
    assert d.needs_review                                                                              # ...but a weak one is still flagged


def test_single_modality_inputs_and_unknown_faces_do_not_invent_presence():
    assert all(d.status == ABSENT for d in fs.fuse(ROSTER).decisions.values())
    only_voice = fs.fuse(ROSTER, None, voice({1: 0.9})).decisions[1]
    assert only_voice.status == PRESENT and not only_voice.needs_review                                # no face run: nothing to disagree with
    unknown = face({}, [FaceOutcome(1, UNKNOWN, None, 0.2, 3, (0, 0, 1, 1))])
    assert fs.fuse(ROSTER, unknown, voice({})).decisions[3].status == ABSENT                           # a doubtful face alone marks nobody


def test_voice_weight_is_configurable(monkeypatch):
    f, v = face({1: 0.5}), voice({1: 0.9})
    base = fs.fuse(ROSTER, f, v).decisions[1].confidence
    monkeypatch.setenv("FUSION_VOICE_WEIGHT", "0"); settings.get_settings.cache_clear()
    assert fs.fuse(ROSTER, f, v).decisions[1].confidence == 0.5 < base


def test_notes_and_rows_cover_every_student_exactly_once():
    f = face({1: 0.9, 3: 0.4}); v = voice({1: 0.8, 4: 0.9})
    res = fs.fuse(ROSTER, f, v)
    rows, records = fs.rows_and_records(ROSTER, res)
    assert [r["student_id"] for r in records] == [r["student_id"] for r in ROSTER] and len(rows) == len(ROSTER)
    assert {"Review", "Why", "Source", "Confidence"} <= set(rows[0])
    assert any("BOTH" in n for n in res.notes) and any("flagged" in n for n in res.notes)
    assert records[0]["source"] == "Face+Voice" and records[5]["status"] == ABSENT and records[5]["source"] is None
