"""Orchestrates face / voice recognition for the UI (galleries loaded once per run; engine chosen by config)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from PIL import Image

from src.config.settings import get_settings
from src.pipelines.face_engine import DetectedFace, FaceRecognitionEngine, get_engine
from src.pipelines import face_quality, liveness, voice_quality
from src.pipelines.face_matching import AMBIGUOUS, RECOGNIZED, UNKNOWN, MatchPolicy, match_face
from src.repositories import student_repository
from src.services.attendance_service import Detection
from src.utils.errors import AIError, ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)

TOO_SMALL = "TOO_SMALL"          # a face was found but is below MIN_FACE_PX: not matched, reported for review
LOW_QUALITY = "LOW_QUALITY"      # blurry / dark / tiny crop below CLASSROOM_MIN_QUALITY: not matched, reported for review


def current_engine() -> FaceRecognitionEngine:
    return get_engine(get_settings().face_engine)


def policy_for(engine: FaceRecognitionEngine) -> MatchPolicy:
    s = get_settings()
    return MatchPolicy(
        metric=engine.metric,
        threshold=s.face_threshold_override if s.face_threshold_override is not None else engine.default_threshold,
        margin=s.face_margin_override if s.face_margin_override is not None else engine.default_margin,
        top_k=max(1, s.face_top_k),
    )


def _faces(engine: FaceRecognitionEngine, image: Image.Image) -> list[DetectedFace]:
    return engine.detect_and_embed(np.asarray(image.convert("RGB")))


# ───────────────────────── enrolment ─────────────────────────
@dataclass(frozen=True)
class FaceSample:
    embedding: list[float]
    model_id: str
    quality: float | None = None      # 0..100, stored with the template


def _single_quality_face(engine: FaceRecognitionEngine, image: Image.Image) -> tuple[DetectedFace, face_quality.QualityReport]:
    """The ONLY face in a photo, after the strict quality gate; otherwise a specific, user-safe reason."""
    arr = np.asarray(image.convert("RGB"))
    found = engine.detect_and_embed(arr)
    if not found:
        raise ValidationError("no face", user_message="We could not find a face in that photo. Face the camera in good light.")
    if len(found) > 1:
        raise ValidationError("many faces", user_message="More than one face was found. Retake the photo with only you in it.")
    face = found[0]
    if face.size < get_settings().min_face_px:
        raise ValidationError("small face", user_message="Your face is too small in the photo. Move closer to the camera.")
    report = face_quality.assess(arr, face.box, face.det_score)
    if not report.ok:
        raise ValidationError("poor quality " + ",".join(report.issues), user_message=" ".join(report.messages()))
    return face, report


def prepare_face_sample(image: Image.Image, engine: FaceRecognitionEngine | None = None) -> FaceSample:
    """Embedding of the ONLY face in a photo (quality-gated). No liveness: use prepare_enrollment_sample for enrolment."""
    engine = engine or current_engine()
    face, report = _single_quality_face(engine, image)
    return FaceSample(face.embedding.tolist(), engine.model_id, report.score)


def liveness_required() -> bool:
    return get_settings().liveness_mode == "challenge"


def new_liveness_challenge() -> tuple[str, str]:
    """(challenge code, instruction text) for the UI to show; the code is passed back to prepare_enrollment_sample."""
    code = liveness.new_challenge()
    return code, liveness.CHALLENGES[code]


def prepare_enrollment_sample(first: Image.Image | None, second: Image.Image | None = None, challenge: str | None = None,
                              engine: FaceRecognitionEngine | None = None) -> FaceSample:
    """Quality-gated sample, plus the movement-challenge liveness check when LIVENESS_MODE=challenge.

    The stored template comes from the first (neutral) photo. See src/pipelines/liveness.py for what the check does and does not prove."""
    if first is None:
        raise ValidationError("no photo", user_message="Please take a photo of your face.")
    engine = engine or current_engine()
    face1, report = _single_quality_face(engine, first)
    if liveness_required():
        if second is None or not challenge:
            raise ValidationError("liveness missing", user_message="Please complete the liveness step: take the second photo as instructed.")
        found = _faces(engine, second)
        if len(found) != 1:
            raise ValidationError("liveness faces", user_message="The second photo must show exactly one face (yours).")
        face2 = found[0]
        same = match_face(face2.embedding, {0: face1.embedding}, MatchPolicy(engine.metric, policy_for(engine).threshold, 0.0, 1))
        if same.status != RECOGNIZED:
            raise ValidationError("liveness identity", user_message="The two photos do not appear to show the same person. Please try again.")
        if liveness.pixel_difference(np.asarray(first.convert("RGB")), np.asarray(second.convert("RGB"))) < liveness.MIN_PIXEL_DIFF:
            raise ValidationError("liveness duplicate", user_message="The second photo is identical to the first. Please take a new photo.")
        answered = liveness.challenge_answered(face1.box, face2.box, challenge)
        if not answered.ok:
            raise ValidationError("liveness challenge", user_message=answered.reason)
        log_event(log, "liveness_passed", challenge=challenge, engine=engine.model_id)
    return FaceSample(face1.embedding.tolist(), engine.model_id, report.score)


def extract_single_face_embedding(image: Image.Image) -> list[float] | None:
    """Back-compat helper: the embedding of the only face, or None unless exactly one usable face is found."""
    try:
        return prepare_face_sample(image).embedding
    except ValidationError:
        return None


def add_my_face_sample(image: Image.Image) -> int:
    """A logged-in student adds another sample (different light/angle) for the active engine. The account is already
    authenticated by password, so the extra sample is quality-gated but needs no liveness challenge."""
    sample = prepare_face_sample(image)
    student_repository.add_face_sample(sample.embedding, sample.model_id, sample.quality)
    return student_repository.my_face_sample_counts().get(sample.model_id, 0)


def my_face_sample_count() -> tuple[str, int]:
    model = current_engine().model_id
    return model, student_repository.my_face_sample_counts().get(model, 0)


# ───────────────────────── attendance ─────────────────────────
@dataclass(frozen=True)
class FaceOutcome:
    photo: int
    status: str                    # RECOGNIZED | UNKNOWN | AMBIGUOUS | TOO_SMALL
    student_id: int | None
    score: float
    candidate_id: int | None
    box: tuple[int, int, int, int]
    quality: float = 0.0


@dataclass
class PhotoAnalysis:
    detections: dict[int, Detection] = field(default_factory=dict)
    faces: list[FaceOutcome] = field(default_factory=list)
    photos_without_faces: list[int] = field(default_factory=list)
    students_without_templates: list[int] = field(default_factory=list)   # enrolled but no sample for the active model
    engine: str = ""

    def count(self, status: str) -> int:
        return sum(1 for f in self.faces if f.status == status)

    def notes(self) -> list[str]:
        out = []
        if self.photos_without_faces:
            out.append("No face found in photo " + ", ".join(map(str, self.photos_without_faces)) + ".")
        if self.count(UNKNOWN):
            out.append(f"{self.count(UNKNOWN)} face(s) did not match anyone enrolled in this subject.")
        if self.count(AMBIGUOUS):
            out.append(f"{self.count(AMBIGUOUS)} face(s) were too close to call between two students and were NOT marked - check manually.")
        if self.count(LOW_QUALITY):
            out.append(f"{self.count(LOW_QUALITY)} face(s) were too blurry, dark or small to identify reliably and were NOT marked - check manually.")
        if self.count(TOO_SMALL):
            out.append(f"{self.count(TOO_SMALL)} face(s) were too small to identify reliably.")
        if self.students_without_templates:
            out.append(f"{len(self.students_without_templates)} enrolled student(s) have no face data for the current recognition model and cannot be recognised.")
        return out


def analyze_photos(images: Iterable[Image.Image], roster: list[dict], engine: FaceRecognitionEngine | None = None) -> PhotoAnalysis:
    """Match every face in every photo against the *enrolled* roster only (gallery loaded once, filtered to the engine's model).

    A student seen in several photos yields a single Detection listing all photos, scored with their best sighting.
    """
    engine = engine or current_engine()
    policy = policy_for(engine)
    roster_ids = [s["student_id"] for s in roster]
    gallery = student_repository.get_face_gallery(roster_ids, engine.model_id)
    min_px = get_settings().min_face_px
    result = PhotoAnalysis(engine=engine.model_id, students_without_templates=[i for i in roster_ids if i not in gallery])
    sightings: dict[int, list[tuple[int, float]]] = {}
    min_quality = get_settings().classroom_min_quality
    for idx, image in enumerate(images, start=1):
        arr = np.asarray(image.convert("RGB"))
        found = engine.detect_and_embed(arr)
        if not found:
            result.photos_without_faces.append(idx)
        for face in found:
            if face.size < min_px:
                result.faces.append(FaceOutcome(idx, TOO_SMALL, None, 0.0, None, face.box))
                continue
            q = face_quality.assess(arr, face.box, face.det_score, min_side=min_px)
            if not face_quality.usable_in_class(q, min_quality):
                result.faces.append(FaceOutcome(idx, LOW_QUALITY, None, 0.0, None, face.box, q.score))
                continue
            m = match_face(face.embedding, gallery, policy)
            result.faces.append(FaceOutcome(idx, m.status, m.student_id, m.score, m.candidate_id, face.box, q.score))
            if m.status == RECOGNIZED:
                sightings.setdefault(m.student_id, []).append((idx, m.score))
    for sid, seen in sightings.items():
        photos = list(dict.fromkeys(f"Photo {i}" for i, _ in seen))
        result.detections[sid] = Detection(sid, ", ".join(photos), round(max(s for _, s in seen), 3))
    log_event(log, "photo_attendance_processed", engine=engine.model_id, recognized=len(result.detections), roster=len(roster),
              unknown=result.count(UNKNOWN), ambiguous=result.count(AMBIGUOUS), small=result.count(TOO_SMALL), low_quality=result.count(LOW_QUALITY))
    return result


def face_stats(a: "PhotoAnalysis") -> dict:
    return {"faces": len(a.faces), "recognized": a.count(RECOGNIZED), "unknown": a.count(UNKNOWN), "ambiguous": a.count(AMBIGUOUS),
            "low_quality": a.count(LOW_QUALITY), "too_small": a.count(TOO_SMALL)}


def voice_stats(a: "VoiceAnalysis") -> dict:
    return {"segments": len(a.segments), "recognized": a.count(RECOGNIZED), "unknown": a.count(UNKNOWN), "ambiguous": a.count(AMBIGUOUS),
            "low_quality": a.count(LOW_QUALITY)}


def detect_faces_in_photos(images: Iterable[Image.Image], roster: list[dict]) -> dict[int, Detection]:
    return analyze_photos(images, roster).detections


# ───────────────────────── voice ─────────────────────────
@dataclass(frozen=True)
class VoiceSample:
    embedding: list[float]
    model_id: str
    quality: float


def _voice_backend(backend=None):
    if backend is not None:
        return backend
    from src.pipelines.voice_pipeline import default_backend
    return default_backend()


def prepare_voice_sample(audio_bytes: bytes, backend=None) -> VoiceSample:
    """Embedding of an enrolment recording after the strict audio-quality gate (speech length, level, clipping, noise)."""
    s, backend = get_settings(), _voice_backend(backend)
    wav = backend.decode(audio_bytes)
    q = voice_quality.assess(wav, s.voice_enrol_seconds, s.voice_min_snr_db)
    if not q.ok:
        raise ValidationError("poor audio " + ",".join(q.issues), user_message=" ".join(q.messages()))
    return VoiceSample(np.asarray(backend.embed(wav), dtype=float).tolist(), backend.model_id, q.score)


def add_my_voice_sample(audio_bytes: bytes, backend=None) -> int:
    sample = prepare_voice_sample(audio_bytes, backend)
    student_repository.add_voice_sample(sample.embedding, sample.model_id, sample.quality)
    return student_repository.my_voice_sample_counts().get(sample.model_id, 0)


def my_voice_sample_count(backend=None) -> tuple[str, int]:
    from src.pipelines.voice_pipeline import DEFAULT_MODEL_ID
    model = backend.model_id if backend is not None else DEFAULT_MODEL_ID      # do not load the model just to count samples
    return model, student_repository.my_voice_sample_counts().get(model, 0)


@dataclass(frozen=True)
class VoiceOutcome:
    start_s: float
    end_s: float
    status: str                 # RECOGNIZED | UNKNOWN | AMBIGUOUS | LOW_QUALITY
    student_id: int | None
    score: float
    quality: float
    candidate_id: int | None = None      # nearest student even when AMBIGUOUS/UNKNOWN (used by fusion)


@dataclass
class VoiceAnalysis:
    detections: dict[int, Detection] = field(default_factory=dict)
    segments: list[VoiceOutcome] = field(default_factory=list)
    students_without_templates: list[int] = field(default_factory=list)
    with_voice: int = 0
    no_speech: bool = False
    global_issues: tuple[str, ...] = ()      # recording-level problems (e.g. NOISY) when no usable speech was found
    model: str = ""

    def count(self, status: str) -> int:
        return sum(1 for f in self.segments if f.status == status)

    def notes(self) -> list[str]:
        out = []
        if self.no_speech and self.global_issues:
            out += voice_quality.MESSAGES.get(self.global_issues[0], "").split("\n")
        elif self.no_speech:
            out.append("No speech was found in the recording.")
        if self.count(UNKNOWN):
            out.append(f"{self.count(UNKNOWN)} speech segment(s) did not match anyone enrolled in this subject.")
        if self.count(AMBIGUOUS):
            out.append(f"{self.count(AMBIGUOUS)} speech segment(s) were too close to call between two students and were NOT marked - check manually.")
        if self.count(LOW_QUALITY):
            out.append(f"{self.count(LOW_QUALITY)} speech segment(s) were too noisy or quiet to identify reliably and were NOT marked.")
        if self.students_without_templates:
            out.append(f"{len(self.students_without_templates)} enrolled student(s) have no voice sample for the current model and cannot be recognised by voice.")
        return out


def voice_policy() -> MatchPolicy:
    s = get_settings()
    return MatchPolicy("cosine", s.voice_threshold, s.voice_margin, 1)


def analyze_voice(audio_bytes: bytes, roster: list[dict], backend=None) -> VoiceAnalysis:
    """Segment a classroom recording into speech runs (long runs are windowed), quality-check each, and match against the
    enrolled roster with the same threshold + runner-up-margin policy as faces. Ambiguous / poor segments are never marked."""
    s, backend = get_settings(), _voice_backend(backend)
    ids = [r["student_id"] for r in roster]
    gallery = student_repository.get_voice_gallery(ids, backend.model_id)
    result = VoiceAnalysis(students_without_templates=[i for i in ids if i not in gallery], with_voice=len(gallery), model=backend.model_id)
    if not gallery:
        return result
    wav = backend.decode(audio_bytes)
    policy = voice_policy()
    spans = voice_quality.speech_intervals(wav, s.min_speech_seconds)
    result.no_speech = not spans
    if not spans:
        result.global_issues = voice_quality.assess(wav, s.min_speech_seconds, s.voice_min_snr_db).issues
    noise = voice_quality.noise_power(wav)
    best: dict[int, float] = {}
    for a, b in spans:
        seg = wav[a:b]
        q = voice_quality.assess(seg, s.min_speech_seconds, s.voice_min_snr_db, noise)
        t0, t1 = a / voice_quality.SR, b / voice_quality.SR
        if q.issues and set(q.issues) - {"TOO_SHORT"}:
            result.segments.append(VoiceOutcome(t0, t1, LOW_QUALITY, None, 0.0, q.score))
            continue
        m = match_face(backend.embed(seg), gallery, policy)       # metric-aware matcher shared with faces
        result.segments.append(VoiceOutcome(t0, t1, m.status, m.student_id, m.score, q.score, m.candidate_id))
        if m.status == RECOGNIZED and m.score > best.get(m.student_id, -1.0):
            best[m.student_id] = m.score
    result.detections = {sid: Detection(sid, "Voice", round(score, 3)) for sid, score in best.items()}
    log_event(log, "voice_attendance_processed", model=backend.model_id, segments=len(spans), recognized=len(best),
              unknown=result.count(UNKNOWN), ambiguous=result.count(AMBIGUOUS), low_quality=result.count(LOW_QUALITY))
    return result


def detect_speakers(audio_bytes: bytes, roster: list[dict]) -> tuple[dict[int, Detection], int]:
    """Back-compat wrapper: (detections, number_of_roster_students_with_voice_samples)."""
    r = analyze_voice(audio_bytes, roster)
    return r.detections, r.with_voice


__all__ = ["extract_single_face_embedding", "prepare_face_sample", "prepare_enrollment_sample", "new_liveness_challenge", "liveness_required", "add_my_face_sample", "analyze_photos", "detect_faces_in_photos",
           "detect_speakers", "analyze_voice", "prepare_voice_sample", "add_my_voice_sample", "my_voice_sample_count", "VoiceAnalysis", "AIError", "PhotoAnalysis", "FaceOutcome", "FaceSample"]
