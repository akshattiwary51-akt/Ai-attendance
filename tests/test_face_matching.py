import numpy as np

from src.pipelines.face_matching import RECOGNIZED, UNKNOWN, best_match

rng = np.random.default_rng(0)
A, B = rng.normal(size=128), rng.normal(size=128)


def noisy(v, scale):
    return v + rng.normal(scale=scale, size=v.shape)


def test_recognizes_enrolled_student_within_threshold():
    m = best_match(noisy(A, 0.01), {1: A.tolist(), 2: B.tolist()}, threshold=0.6)
    assert (m.student_id, m.status) == (1, RECOGNIZED)


def test_unknown_face_is_not_assigned_to_closest_student():
    stranger = rng.normal(size=128)
    m = best_match(stranger, {1: A.tolist(), 2: B.tolist()}, threshold=0.6)
    assert m.student_id is None and m.status == UNKNOWN


def test_multiple_embeddings_per_student_use_closest_sample():
    far, near = noisy(A, 2.0), noisy(A, 0.01)
    m = best_match(noisy(A, 0.01), {1: [far.tolist(), near.tolist()]}, threshold=0.6)
    assert m.student_id == 1


def test_empty_gallery_is_unknown():
    assert best_match(A, {}, 0.6).status == UNKNOWN


def test_wrong_dimension_embeddings_are_skipped():
    assert best_match(A, {1: [0.1, 0.2]}, 0.6).status == UNKNOWN


def test_threshold_is_respected_exactly():
    v = A.copy()
    w = A.copy(); w[0] += 0.5
    assert best_match(w, {1: v.tolist()}, 0.5).status == RECOGNIZED
    assert best_match(w, {1: v.tolist()}, 0.49).status == UNKNOWN
