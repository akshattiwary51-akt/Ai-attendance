"""Real engines on a real photograph (skimage's bundled astronaut image). Skipped when a model is not installed."""
import os
import pathlib

import numpy as np
import pytest
from PIL import Image

from src.pipelines import onnx_engine as oe
from src.pipelines.face_engine import available_engines, get_engine, reset_engine_cache
from src.utils.errors import AIError

skimage_data = pytest.importorskip("skimage.data")
MODELS = pathlib.Path(os.environ.get("ONNX_MODEL_DIR", "/home/claude/models"))
IMG = skimage_data.astronaut()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ONNX_MODEL_DIR", str(MODELS))
    reset_engine_cache()


def engine_or_skip(name):
    try:
        return get_engine(name)
    except AIError:
        pytest.skip(f"{name} models not installed")


def test_registry_lists_both_engines():
    assert {"dlib", "onnx"} <= set(available_engines())


def test_onnx_missing_models_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path)); reset_engine_cache()
    with pytest.raises(AIError) as ei:
        get_engine("onnx")
    assert "ONNX_MODEL_DIR" in ei.value.user_message


def test_onnx_detects_the_face_and_embeds_stably():
    e = engine_or_skip("onnx")
    faces = e.detect_and_embed(IMG)
    assert len(faces) == 1 and faces[0].embedding.shape == (512,) and abs(np.linalg.norm(faces[0].embedding) - 1) < 1e-6
    l, t, r, b = faces[0].box
    assert 150 < l < 200 and 40 < t < 90 and r - l > 60                      # around the astronaut's face
    dim = np.clip(IMG.astype(float) * 0.7 + 10, 0, 255).astype(np.uint8)
    small = np.asarray(Image.fromarray(IMG).resize((320, 320)))
    for variant in (dim, small):
        v = e.detect_and_embed(variant)
        assert len(v) >= 1 and float(faces[0].embedding @ max(v, key=lambda f: f.det_score).embedding) > 0.8


def test_onnx_returns_nothing_for_a_blank_image():
    e = engine_or_skip("onnx")
    assert e.detect_and_embed(np.full((300, 300, 3), 127, np.uint8)) == []


def test_dlib_embeds_the_face_stably():
    e = engine_or_skip("dlib")
    faces = e.detect_and_embed(IMG)
    assert faces and faces[0].embedding.shape == (128,)
    dim = np.clip(IMG.astype(float) * 0.7 + 10, 0, 255).astype(np.uint8)
    d = min(np.linalg.norm(faces[0].embedding - f.embedding) for f in e.detect_and_embed(dim))
    assert d < 0.3                                                          # same person, different exposure << 0.6 threshold


def test_similarity_transform_recovers_known_transform():
    src = oe.ARCFACE_TEMPLATE
    th = 0.3; R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    moved = 2.0 * src @ R.T + np.array([10, -5])
    m = oe.similarity_transform(moved, src)
    back = (m[:, :2] @ moved.T).T + m[:, 2]
    assert np.allclose(back, src, atol=1e-6)


def test_nms_keeps_best_of_overlapping_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], float)
    assert sorted(oe.nms(boxes, np.array([0.9, 0.8, 0.7]), 0.4)) == [0, 2]
