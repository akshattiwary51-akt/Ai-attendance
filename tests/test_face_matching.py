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


# ───── Phase 5: metric-aware matching ─────
import pytest  # noqa: E402

from src.pipelines.face_matching import AMBIGUOUS, MatchPolicy, match_face  # noqa: E402

EUC = MatchPolicy("euclidean", 0.6, margin=0.05)
COS = MatchPolicy("cosine", 0.4, margin=0.05)


def unit(v):
    return v / np.linalg.norm(v)


def test_euclidean_recognised_unknown_and_empty_gallery():
    assert match_face(noisy(A, 0.01), {1: A.tolist(), 2: B.tolist()}, EUC).student_id == 1
    far = match_face(rng.normal(size=128), {1: A.tolist()}, EUC)
    assert far.status == UNKNOWN and far.student_id is None and far.candidate_id == 1
    e = match_face(A, {}, EUC)
    assert e.status == UNKNOWN and e.score == 0.0


def test_cosine_recognised_and_unknown():
    a, b = unit(rng.normal(size=512)), unit(rng.normal(size=512))
    assert match_face(unit(a + rng.normal(scale=0.01, size=512)), {1: [a.tolist()], 2: [b.tolist()]}, COS).student_id == 1
    assert match_face(unit(rng.normal(size=512)), {1: [a.tolist()]}, COS).status == UNKNOWN


def test_cosine_is_scale_invariant():
    a = rng.normal(size=512)
    assert match_face(a * 7.0, {1: [(a * 0.3).tolist()]}, COS).student_id == 1


def test_margin_makes_close_call_ambiguous_and_zero_margin_does_not():
    base = rng.normal(size=128)
    gallery = {1: (base + 0.01).tolist(), 2: (base - 0.01).tolist()}
    assert match_face(base, gallery, EUC).status == AMBIGUOUS
    assert match_face(base, gallery, MatchPolicy("euclidean", 0.6, margin=0.0)).status == RECOGNIZED


def test_same_student_samples_never_make_a_match_ambiguous():
    base = rng.normal(size=128)
    r = match_face(base, {1: [(base + 0.01).tolist(), (base - 0.01).tolist()]}, EUC)     # runner-up is per STUDENT, not per sample
    assert r.status == RECOGNIZED and r.student_id == 1 and r.runner_up_id is None


def test_top_k_averages_samples():
    base = rng.normal(size=128)
    gallery = {1: [base.tolist(), (base + 3.0).tolist()]}
    assert match_face(base, gallery, MatchPolicy("euclidean", 0.6, 0.0, top_k=1)).status == RECOGNIZED
    assert match_face(base, gallery, MatchPolicy("euclidean", 0.6, 0.0, top_k=2)).status == UNKNOWN   # a poor second sample drags the mean


def test_wrong_dimension_gallery_entries_are_skipped_not_crashing():
    r = match_face(rng.normal(size=128), {1: rng.normal(size=512).tolist()}, EUC)
    assert r.status == UNKNOWN and r.candidate_id is None


@pytest.mark.parametrize("raw,score", [(0.0, 1.0), (0.6, 0.5), (1.2, 0.0), (5.0, 0.0)])
def test_euclidean_scores_are_normalised(raw, score):
    from src.pipelines.face_matching import _to_score
    assert _to_score(raw, EUC) == pytest.approx(score)
