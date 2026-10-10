import numpy as np
import pytest
from PIL import Image

from src.config import settings
from src.pipelines.face_engine import COSINE, EUCLIDEAN, DetectedFace, FaceRecognitionEngine
from src.repositories import student_repository
from src.services import recognition_service as rs
from src.utils.errors import ValidationError

rng = np.random.default_rng(1)
FACES = {1: rng.normal(size=128), 2: rng.normal(size=128), 3: rng.normal(size=128)}
skimage_data = pytest.importorskip("skimage.data")
IMG = Image.fromarray(skimage_data.astronaut())       # a real, sharp, well-lit photo so the quality gate has something to judge
BOX = (165, 10, 300, 160)                              # the astronaut's face


class FakeEngine(FaceRecognitionEngine):
    model_id, metric, default_threshold, default_margin = "fake-128", EUCLIDEAN, 0.6, 0.05

    def __init__(self, per_image):
        self.per_image, self.calls = iter(per_image), 0

    def detect_and_embed(self, image):
        self.calls += 1
        return [f if isinstance(f, DetectedFace) else DetectedFace(BOX, np.asarray(f)) for f in next(self.per_image)]


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def patch(monkeypatch, gallery_ids=None):
    asked = {}
    def gallery(ids=None, model=None):
        asked["ids"], asked["model"] = ids, model
        return {i: FACES[i].tolist() for i in (ids or FACES) if i in FACES}
    monkeypatch.setattr(student_repository, "get_face_gallery", gallery)
    return asked


def test_student_in_three_photos_yields_one_detection_listing_photos(monkeypatch):
    patch(monkeypatch)
    eng = FakeEngine([[FACES[1], FACES[2]], [FACES[1]], [FACES[1] + 0.01]])
    out = rs.analyze_photos([IMG] * 3, [{"student_id": i} for i in (1, 2, 3)], eng).detections
    assert set(out) == {1, 2}
    assert out[1].source == "Photo 1, Photo 2, Photo 3" and out[2].source == "Photo 1"
    assert 0.9 < out[1].confidence <= 1.0                       # best sighting, normalised 0..1


def test_only_enrolled_students_are_loaded_and_matched_for_this_model(monkeypatch):
    asked = patch(monkeypatch)
    res = rs.analyze_photos([IMG], [{"student_id": 1}, {"student_id": 2}], FakeEngine([[FACES[3]]]))   # 3 is NOT enrolled
    assert asked == {"ids": [1, 2], "model": "fake-128"} and res.detections == {}


def test_stranger_is_reported_unknown_not_attributed(monkeypatch):
    patch(monkeypatch)
    res = rs.analyze_photos([IMG], [{"student_id": 1}], FakeEngine([[rng.normal(size=128)]]))
    assert res.detections == {} and res.count("UNKNOWN") == 1
    assert any("did not match" in n for n in res.notes())


def test_two_lookalike_students_are_ambiguous_and_not_marked(monkeypatch):
    base = rng.normal(size=128)
    monkeypatch.setattr(student_repository, "get_face_gallery", lambda ids=None, model=None: {1: (base + 0.01).tolist(), 2: (base - 0.01).tolist()})
    res = rs.analyze_photos([IMG], [{"student_id": 1}, {"student_id": 2}], FakeEngine([[base]]))
    assert res.detections == {} and res.count("AMBIGUOUS") == 1
    assert any("too close to call" in n for n in res.notes())


def test_tiny_faces_are_reported_not_matched(monkeypatch):
    patch(monkeypatch)
    tiny = DetectedFace((0, 0, 10, 10), FACES[1])
    res = rs.analyze_photos([IMG], [{"student_id": 1}], FakeEngine([[tiny]]))
    assert res.detections == {} and res.count("TOO_SMALL") == 1


def test_photo_without_faces_and_students_without_templates_are_reported(monkeypatch):
    patch(monkeypatch)
    res = rs.analyze_photos([IMG, IMG], [{"student_id": 1}, {"student_id": 9}], FakeEngine([[], [FACES[1]]]))
    assert res.photos_without_faces == [1] and res.students_without_templates == [9]
    notes = " ".join(res.notes())
    assert "No face found in photo 1" in notes and "no face data" in notes


def test_gallery_loaded_once_not_per_image(monkeypatch):
    calls = []
    monkeypatch.setattr(student_repository, "get_face_gallery", lambda ids=None, model=None: calls.append(1) or {})
    eng = FakeEngine([[]] * 5)
    rs.analyze_photos([IMG] * 5, [{"student_id": 1}], eng)
    assert len(calls) == 1 and eng.calls == 5


def test_prepare_face_sample_gives_specific_reasons():
    ok = DetectedFace(BOX, FACES[1])
    assert rs.prepare_face_sample(IMG, FakeEngine([[ok]])).model_id == "fake-128"
    for faces, text in (([], "could not find a face"), ([ok, ok], "More than one face"), ([DetectedFace((0, 0, 8, 8), FACES[1])], "too small")):
        with pytest.raises(ValidationError) as ei:
            rs.prepare_face_sample(IMG, FakeEngine([faces]))
        assert text in ei.value.user_message
    assert rs.extract_single_face_embedding.__name__            # back-compat helper still exported


def test_engine_selection_and_threshold_overrides(monkeypatch):
    monkeypatch.setenv("FACE_THRESHOLD", "0.35"); monkeypatch.setenv("FACE_MARGIN", "0.0"); monkeypatch.setenv("FACE_TOP_K", "2")
    settings.get_settings.cache_clear()
    p = rs.policy_for(FakeEngine([]))
    assert (p.threshold, p.margin, p.top_k, p.metric) == (0.35, 0.0, 2, EUCLIDEAN)
    monkeypatch.delenv("FACE_THRESHOLD"); monkeypatch.delenv("FACE_MARGIN"); monkeypatch.delenv("FACE_TOP_K")
    settings.get_settings.cache_clear()
    p = rs.policy_for(FakeEngine([]))
    assert (p.threshold, p.margin, p.top_k) == (0.6, 0.05, 1)


def test_unknown_engine_name_is_a_configuration_error(monkeypatch):
    from src.pipelines.face_engine import get_engine
    from src.utils.errors import ConfigurationError
    with pytest.raises(ConfigurationError):
        get_engine("nope")
