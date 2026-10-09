import numpy as np

from src.pipelines.voice_matching import cosine_similarity, identify_speaker, select_segments

v1 = np.array([1.0, 0.0, 0.0]); v2 = np.array([0.0, 1.0, 0.0])


def test_cosine():
    assert cosine_similarity(v1, v1) == 1.0 and cosine_similarity(v1, v2) == 0.0
    assert cosine_similarity([0, 0, 0], v1) == 0.0


def test_identify_above_threshold():
    sid, score = identify_speaker(v1, {1: v1.tolist(), 2: v2.tolist()}, 0.65)
    assert sid == 1 and score > 0.99


def test_below_threshold_is_unknown_even_if_positive_score():
    sid, score = identify_speaker(np.array([1.0, 0.3, 0.0]), {2: v2.tolist()}, 0.65)
    assert sid is None and 0 < score < 0.65


def test_dimension_mismatch_and_empty():
    assert identify_speaker(v1, {1: [1.0, 2.0]}, 0.5)[0] is None
    assert identify_speaker(v1, {}, 0.5)[0] is None


def test_select_segments_drops_short_speech():
    assert select_segments([(0, 4000), (0, 16000)], 16000, 0.5) == [(0, 16000)]
