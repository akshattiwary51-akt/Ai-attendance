import numpy as np

from src.repositories import student_repository
from src.services import recognition_service as rs

rng = np.random.default_rng(1)
FACES = {1: rng.normal(size=128), 2: rng.normal(size=128), 3: rng.normal(size=128)}


def patch(monkeypatch, per_image):
    asked = {}
    monkeypatch.setattr(student_repository, "get_face_gallery",
                        lambda ids=None: asked.setdefault("ids", ids) and {i: FACES[i].tolist() for i in (ids or FACES)})
    it = iter(per_image)
    monkeypatch.setattr(rs, "_embeddings", lambda image: next(it))
    return asked


def test_student_in_three_photos_yields_one_detection_listing_photos(monkeypatch):
    patch(monkeypatch, [[FACES[1], FACES[2]], [FACES[1]], [FACES[1] + 0.01]])
    out = rs.detect_faces_in_photos([object()] * 3, [{"student_id": 1}, {"student_id": 2}, {"student_id": 3}])
    assert set(out) == {1, 2}
    assert out[1].source == "Photo 1, Photo 2, Photo 3" and out[2].source == "Photo 1"


def test_only_enrolled_students_are_loaded_and_matched(monkeypatch):
    asked = patch(monkeypatch, [[FACES[3]]])           # student 3 is NOT enrolled
    out = rs.detect_faces_in_photos([object()], [{"student_id": 1}, {"student_id": 2}])
    assert asked["ids"] == [1, 2] and out == {}


def test_stranger_face_is_not_attributed(monkeypatch):
    patch(monkeypatch, [[rng.normal(size=128)]])
    assert rs.detect_faces_in_photos([object()], [{"student_id": 1}]) == {}


def test_gallery_loaded_once_not_per_image(monkeypatch):
    calls = []
    monkeypatch.setattr(student_repository, "get_face_gallery", lambda ids=None: calls.append(1) or {})
    monkeypatch.setattr(rs, "_embeddings", lambda image: [])
    rs.detect_faces_in_photos([object()] * 5, [{"student_id": 1}])
    assert len(calls) == 1
