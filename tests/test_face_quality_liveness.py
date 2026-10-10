"""Face quality metrics, the strict enrolment gate, the lenient classroom gate and the liveness challenge."""
import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter

from src.config import settings
from src.pipelines import face_quality as fq, liveness
from src.pipelines.face_engine import EUCLIDEAN, DetectedFace, FaceRecognitionEngine
from src.repositories import student_repository
from src.services import recognition_service as rs
from src.utils.errors import ValidationError

skimage_data = pytest.importorskip("skimage.data")
ASTRO = Image.fromarray(skimage_data.astronaut())
BOX = (165, 10, 300, 160)
EMB = np.random.default_rng(3).normal(size=128)


def report(img, box=BOX, det=1.0, **kw):
    return fq.assess(np.asarray(img), box, det, **kw)


# ───────── metrics ─────────
def test_sharp_well_lit_photo_passes():
    r = report(ASTRO)
    assert r.ok and r.score > 85 and r.size == 135


@pytest.mark.parametrize("make, code", [
    (lambda: ASTRO.filter(ImageFilter.GaussianBlur(6)), "BLURRY"),
    (lambda: ImageEnhance.Brightness(ASTRO).enhance(0.25), "TOO_DARK"),
    (lambda: ImageEnhance.Brightness(ASTRO).enhance(2.8), "TOO_BRIGHT"),
])
def test_each_defect_is_detected_with_a_user_message(make, code):
    r = report(make())
    assert code in r.issues and not r.ok
    assert all(m for m in r.messages())


def test_blur_lowers_score_monotonically():
    scores = [report(ASTRO.filter(ImageFilter.GaussianBlur(s))).score for s in (0.01, 1.5, 3, 6)]
    assert scores == sorted(scores, reverse=True)


def test_small_cut_off_and_low_confidence_faces():
    assert "TOO_SMALL" in report(ASTRO, (170, 20, 200, 50)).issues
    assert "CUT_OFF" in report(ASTRO, (0, 10, 130, 160)).issues
    assert "LOW_CONFIDENCE" in report(ASTRO, det=0.3).issues
    assert report(ASTRO, (10, 10, 12, 12)).issues == ("TOO_SMALL",)           # degenerate crop never crashes
    assert report(ASTRO, (-50, -50, 40, 40)).issues                            # box partly outside the frame never crashes


def test_flat_grey_image_is_low_contrast_and_blurry():
    flat = Image.new("RGB", (300, 300), (128, 128, 128))
    r = report(flat, (50, 50, 200, 200))
    assert "LOW_CONTRAST" in r.issues and "BLURRY" in r.issues


def test_class_gate_is_lenient_but_rejects_hopeless_crops():
    assert fq.usable_in_class(report(ASTRO), 35)
    assert not fq.usable_in_class(report(ASTRO.filter(ImageFilter.GaussianBlur(8)), (170, 20, 200, 50)), 60)


# ───────── enrolment service ─────────
class Eng(FaceRecognitionEngine):
    model_id, metric, default_threshold, default_margin = "fake-128", EUCLIDEAN, 0.6, 0.05

    def __init__(self, per_image):
        self.per_image = iter(per_image)

    def detect_and_embed(self, image):
        return [DetectedFace(b, np.asarray(e)) for b, e in next(self.per_image)]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def test_blurry_enrolment_photo_is_rejected_with_reason():
    blurry = ASTRO.filter(ImageFilter.GaussianBlur(6))
    with pytest.raises(ValidationError) as ei:
        rs.prepare_face_sample(blurry, Eng([[(BOX, EMB)]]))
    assert "blurry" in ei.value.user_message.lower()


def test_good_sample_carries_quality_score():
    s = rs.prepare_face_sample(ASTRO, Eng([[(BOX, EMB)]]))
    assert s.model_id == "fake-128" and 85 < s.quality <= 100


def test_add_sample_stores_the_quality(monkeypatch):
    saved = {}
    monkeypatch.setattr(rs, "current_engine", lambda: Eng([[(BOX, EMB)]]))
    monkeypatch.setattr(student_repository, "add_face_sample", lambda e, m, q=None: saved.update(model=m, q=q))
    monkeypatch.setattr(student_repository, "my_face_sample_counts", lambda: {"fake-128": 2})
    assert rs.add_my_face_sample(ASTRO) == 2 and saved["model"] == "fake-128" and saved["q"] > 85


# ───────── liveness ─────────
def shifted(img, dx=0, dy=0):
    """The same scene moved inside the frame (as a person moving their head would)."""
    return img.transform(img.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy), fillcolor=(90, 90, 90))


def test_challenge_codes_are_random_and_known():
    seen = {liveness.new_challenge() for _ in range(100)}
    assert seen == set(liveness.CHALLENGES)


@pytest.mark.parametrize("challenge, box2, ok", [
    ("closer", (150, 0, 330, 180), True), ("closer", (170, 12, 296, 158), False),
    ("back", (180, 30, 280, 130), True), ("back", (150, 0, 330, 180), False),
    ("up", (165, -30, 300, 120), True), ("up", (165, 40, 300, 190), False),
    ("down", (165, 40, 300, 190), True), ("down", (165, 12, 300, 162), False),
])
def test_challenge_geometry(challenge, box2, ok):
    assert liveness.challenge_answered((165, 10, 300, 160), box2, challenge).ok is ok


def test_unknown_challenge_fails_closed():
    assert not liveness.challenge_answered(BOX, BOX, "wave").ok


def test_pixel_difference_detects_same_picture():
    a = np.asarray(ASTRO)
    assert liveness.pixel_difference(a, a) == 0
    assert liveness.pixel_difference(a, np.asarray(shifted(ASTRO, 25))) > liveness.MIN_PIXEL_DIFF


CLOSER_BOX = (150, 0, 330, 180)          # 180 wide vs 135: x1.33 closer. The box touches the top edge, so use a taller frame below.


def padded(img):
    """Pad the frame so the 'closer' face is not cut off by the frame edge."""
    out = Image.new("RGB", (img.width + 100, img.height + 100), (90, 90, 90))
    out.paste(img, (50, 50)); return out


def run(first, second, boxes, challenge, e1=EMB, e2=EMB):
    return rs.prepare_enrollment_sample(first, second, challenge, Eng([[(boxes[0], e1)], [(boxes[1], e2)]]))


def test_liveness_passes_when_challenge_is_answered():
    b1 = (215, 60, 350, 210); b2 = (200, 45, 380, 225)
    s = run(padded(ASTRO), padded(shifted(ASTRO, 10)), (b1, b2), "closer")
    assert s.quality > 80


def test_liveness_failures_are_specific():
    b1 = (215, 60, 350, 210); b2 = (200, 45, 380, 225)
    with pytest.raises(ValidationError) as ei:                           # a second photo that does not move as asked
        run(padded(ASTRO), padded(shifted(ASTRO, 10)), (b1, b1), "closer")
    assert "movement" in ei.value.user_message
    with pytest.raises(ValidationError) as ei:                           # same picture submitted twice
        run(padded(ASTRO), padded(ASTRO), (b1, b2), "closer")
    assert "identical" in ei.value.user_message
    with pytest.raises(ValidationError) as ei:                           # a different person in the second photo
        run(padded(ASTRO), padded(shifted(ASTRO, 10)), (b1, b2), "closer", e2=np.random.default_rng(9).normal(size=128))
    assert "same person" in ei.value.user_message
    with pytest.raises(ValidationError) as ei:                           # second photo missing
        rs.prepare_enrollment_sample(padded(ASTRO), None, "closer", Eng([[(b1, EMB)]]))
    assert "liveness" in ei.value.user_message.lower()


def test_liveness_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("LIVENESS_MODE", "off"); settings.get_settings.cache_clear()
    assert not rs.liveness_required()
    assert rs.prepare_enrollment_sample(padded(ASTRO), None, None, Eng([[((215, 60, 350, 210), EMB)]])).quality > 80


# ───────── classroom ─────────
def test_blurry_classroom_face_is_flagged_not_marked(monkeypatch):
    monkeypatch.setattr(student_repository, "get_face_gallery", lambda ids=None, model=None: {1: EMB.tolist()})
    blurry = ASTRO.filter(ImageFilter.GaussianBlur(9))
    res = rs.analyze_photos([ASTRO, blurry], [{"student_id": 1}], Eng([[(BOX, EMB)], [((170, 20, 215, 70), EMB)]]))
    assert set(res.detections) == {1} and res.detections[1].source == "Photo 1"
    assert res.count(rs.LOW_QUALITY) == 1 and any("NOT marked" in n and "blurry" in n for n in res.notes())
