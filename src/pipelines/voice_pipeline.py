"""Resemblyzer baseline voice embedding extraction (lazy imports, no UI side effects)."""
from __future__ import annotations

import io

import streamlit as st

from src.config.settings import get_settings
from src.pipelines.voice_matching import identify_speaker, select_segments
from src.utils.errors import AIError
from src.utils.logging import get_logger

log = get_logger(__name__)
SAMPLE_RATE = 16000


@st.cache_resource(show_spinner=False)
def load_voice_encoder():
    try:
        from resemblyzer import VoiceEncoder
    except ImportError as exc:
        raise AIError("resemblyzer missing", user_message="Voice recognition models are not installed on this server.") from exc
    return VoiceEncoder()


def _decode(audio_bytes: bytes):
    import librosa

    try:
        audio, _ = librosa.load(io.BytesIO(audio_bytes), sr=SAMPLE_RATE)
    except Exception as exc:  # librosa/soundfile/audioread raise many unrelated types
        log.error("audio_decode_failed type=%s", type(exc).__name__)
        raise AIError("audio decode failed", user_message="Could not read that audio recording.") from exc
    if audio.size == 0:
        raise AIError("empty audio", user_message="The recording is empty.")
    return audio


def get_voice_embedding(audio_bytes: bytes) -> list[float]:
    from resemblyzer import preprocess_wav

    encoder = load_voice_encoder()
    wav = preprocess_wav(_decode(audio_bytes))
    if wav.size < SAMPLE_RATE * get_settings().min_speech_seconds:
        raise AIError("too little speech", user_message="Not enough speech detected. Please record a longer phrase.")
    return encoder.embed_utterance(wav).tolist()


def process_bulk_audio(audio_bytes: bytes, candidates: dict[int, list[float]], threshold: float | None = None) -> dict[int, float]:
    """Identify enrolled speakers in a classroom recording -> {student_id: best_similarity}."""
    import librosa
    from resemblyzer import preprocess_wav

    settings = get_settings()
    threshold = settings.voice_threshold if threshold is None else threshold
    encoder = load_voice_encoder()
    audio = _decode(audio_bytes)
    segments = select_segments(librosa.effects.split(audio, top_db=30), SAMPLE_RATE, settings.min_speech_seconds)

    found: dict[int, float] = {}
    for start, end in segments:
        wav = preprocess_wav(audio[start:end])
        if wav.size == 0:
            continue
        student_id, score = identify_speaker(encoder.embed_utterance(wav), candidates, threshold)
        if student_id is not None and score > found.get(student_id, -1.0):
            found[student_id] = score
    return found
