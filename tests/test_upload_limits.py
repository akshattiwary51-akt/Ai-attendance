"""Upload hardening: size, pixel and duration bounds apply before any analysis."""
import io

import numpy as np
import pytest
from PIL import Image

from src.config import settings
from src.services import recognition_service as rs
from src.utils.errors import ValidationError
from src.utils.images import load_image


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def png(w, h):
    b = io.BytesIO(); Image.new("RGB", (w, h)).save(b, "PNG"); b.seek(0); return b


class Backend:
    model_id = "fake"
    def __init__(self, n=16000): self.n = n; self.called = False
    def decode(self, data): self.called = True; return np.zeros(self.n)


def test_image_with_too_many_pixels_is_rejected_from_the_header(monkeypatch):
    monkeypatch.setenv("MAX_IMAGE_PIXELS", "10000")
    with pytest.raises(ValidationError):
        load_image(png(200, 200))


def test_garbage_and_oversize_images_are_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        load_image(io.BytesIO(b"not an image"))
    big = png(10, 10); big.size = 11 * 1024 * 1024
    with pytest.raises(ValidationError):
        load_image(big)


def test_normal_image_is_accepted_and_bounded(monkeypatch):
    monkeypatch.setenv("MAX_IMAGE_SIDE", "50")
    assert max(load_image(png(120, 80)).size) <= 50


def test_empty_and_oversize_audio_never_reach_the_decoder():
    b = Backend()
    with pytest.raises(ValidationError):
        rs._decode_audio(b, b"")
    with pytest.raises(ValidationError):
        rs._decode_audio(b, b"x" * (16 * 1024 * 1024))
    assert not b.called


def test_overlong_audio_is_rejected_after_decoding(monkeypatch):
    monkeypatch.setenv("MAX_AUDIO_SECONDS", "1")
    with pytest.raises(ValidationError):
        rs._decode_audio(Backend(n=16000 * 2), b"x")
    assert len(rs._decode_audio(Backend(n=16000), b"x")) == 16000
