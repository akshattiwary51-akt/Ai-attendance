"""Voice backend (Resemblyzer baseline). Heavy imports are lazy so the rest of the app and the tests never need them.

A backend turns encoded audio into a 16 kHz mono float waveform (`decode`) and a waveform into an embedding (`embed`).
Recognition logic lives in recognition_service and is tested with fake backends."""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Protocol

import numpy as np

from src.utils.errors import AIError
from src.utils.logging import get_logger

log = get_logger(__name__)
SAMPLE_RATE = 16000
DEFAULT_MODEL_ID = "resemblyzer"      # known without loading the model


class VoiceBackend(Protocol):
    model_id: str

    def decode(self, data: bytes) -> np.ndarray: ...
    def embed(self, wav: np.ndarray) -> np.ndarray: ...


class ResemblyzerBackend:
    model_id = DEFAULT_MODEL_ID

    def __init__(self):
        try:
            from resemblyzer import VoiceEncoder
        except ImportError as exc:
            raise AIError("resemblyzer missing", user_message="Voice recognition models are not installed on this server.") from exc
        self._encoder = VoiceEncoder()

    def decode(self, data: bytes) -> np.ndarray:
        import librosa
        try:
            audio, _ = librosa.load(io.BytesIO(data), sr=SAMPLE_RATE)
        except Exception as exc:  # librosa/soundfile/audioread raise many unrelated types
            log.error("audio_decode_failed type=%s", type(exc).__name__)
            raise AIError("audio decode failed", user_message="Could not read that audio recording.") from exc
        if audio.size == 0:
            raise AIError("empty audio", user_message="The recording is empty.")
        return audio

    def embed(self, wav: np.ndarray) -> np.ndarray:
        from resemblyzer import preprocess_wav
        return self._encoder.embed_utterance(preprocess_wav(wav))


@lru_cache(maxsize=1)
def default_backend() -> VoiceBackend:
    return ResemblyzerBackend()
