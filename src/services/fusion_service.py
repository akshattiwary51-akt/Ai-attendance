"""Multimodal fusion: combine the face and voice evidence of ONE classroom session into one decision per student.

Deliberately rule-based and explainable (no learned weights - there is no labelled data to learn them from):

  face + voice both recognise the student     PRESENT, confidence = noisy-OR of the face score and the weighted voice score
  face recognises, voice does not             PRESENT (a student need not speak), confidence = face score
  voice recognises, face does not             policy FUSION_VOICE_ONLY: review (PRESENT, flagged) | accept | reject (ABSENT, noted)
  a face was AMBIGUOUS/UNKNOWN but its nearest   voice resolves the ambiguity: PRESENT, flagged for review
    student is the one the voice recognised
  nobody recognises the student               ABSENT

A single-modality match below FUSION_REVIEW_BELOW is flagged for review. Scores are each engine's normalised 0..1 match score,
not calibrated probabilities, so the combined number is a ranking aid for the teacher, not a probability of presence.
Nothing is saved here: the teacher reviews and confirms (and can still correct records afterwards, audited)."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config.settings import get_settings
from src.pipelines.face_matching import AMBIGUOUS, UNKNOWN
from src.services.attendance_service import ABSENT, PRESENT, STATUS_LABEL


@dataclass(frozen=True)
class FusedDecision:
    student_id: int
    status: str                  # PRESENT | ABSENT
    confidence: float | None
    source: str | None           # "Face" | "Voice" | "Face+Voice" | "Voice resolves face" | None
    needs_review: bool = False
    reason: str = ""


@dataclass
class FusionResult:
    decisions: dict[int, FusedDecision] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        d = self.decisions.values()
        return {"present": sum(x.status == PRESENT for x in d), "review": sum(x.needs_review for x in d),
                "both": sum(x.source == "Face+Voice" for x in d)}


def noisy_or(a: float, b: float) -> float:
    return 1.0 - (1.0 - a) * (1.0 - b)


def fuse(roster: list[dict], face=None, voice=None) -> FusionResult:
    """face: recognition_service.PhotoAnalysis | None; voice: recognition_service.VoiceAnalysis | None."""
    s = get_settings()
    w, review_below, policy = s.fusion_voice_weight, s.fusion_review_below, s.fusion_voice_only
    both_ran = face is not None and voice is not None
    face_det = face.detections if face else {}
    voice_det = voice.detections if voice else {}
    face_candidates: dict[int, float] = {}                      # students nearest to an ambiguous/unknown face
    for f in (face.faces if face else []):
        if f.status in (AMBIGUOUS, UNKNOWN) and f.candidate_id is not None:
            face_candidates[f.candidate_id] = max(face_candidates.get(f.candidate_id, 0.0), f.score)

    out = FusionResult()
    voice_only_rejected = 0
    for r in roster:
        sid = r["student_id"]
        f, v = face_det.get(sid), voice_det.get(sid)
        fs, vs = (f.confidence or 0.0) if f else 0.0, (v.confidence or 0.0) if v else 0.0
        if f and v:
            d = FusedDecision(sid, PRESENT, round(noisy_or(fs, w * vs), 3), "Face+Voice", False, "Face and voice agree.")
        elif f:
            low = fs < review_below
            d = FusedDecision(sid, PRESENT, round(fs, 3), "Face", low, "Face match is weak." if low else "Face match.")
        elif v and sid in face_candidates:
            conf = round(noisy_or(0.5 * face_candidates[sid], w * vs), 3)
            d = FusedDecision(sid, PRESENT, conf, "Voice resolves face", True, "Voice matched the student a doubtful face was closest to.")
        elif v:
            if both_ran and policy == "reject":
                voice_only_rejected += 1
                d = FusedDecision(sid, ABSENT, None, None, False, "Voice-only match rejected by policy.")
            else:
                flag = both_ran and policy != "accept" or vs < review_below
                d = FusedDecision(sid, PRESENT, round(w * vs, 3), "Voice", flag,
                                  "Voice only: no face evidence." if both_ran else "Voice match.")
        else:
            d = FusedDecision(sid, ABSENT, None, None, False, "No face or voice match.")
        out.decisions[sid] = d

    c = out.counts()
    if c["both"]:
        out.notes.append(f"{c['both']} student(s) were recognised by BOTH face and voice.")
    if c["review"]:
        out.notes.append(f"{c['review']} student(s) are marked present on weaker evidence and flagged ⚠ - please check them.")
    if voice_only_rejected:
        out.notes.append(f"{voice_only_rejected} student(s) were heard but not seen and were left absent (voice-only matches are rejected by policy).")
    for a in (face.notes() if face else []):
        out.notes.append("Face: " + a)
    for a in (voice.notes() if voice else []):
        out.notes.append("Voice: " + a)
    return out


def rows_and_records(roster: list[dict], result: FusionResult) -> tuple[list[dict], list[dict]]:
    """(display_rows, records) like attendance_service.build_attendance_rows, one per student, with a Review column."""
    display, records = [], []
    for r in roster:
        d = result.decisions[r["student_id"]]
        display.append({"Name": r["name"], "ID": r["student_id"], "Source": d.source or "-", "Confidence": d.confidence,
                        "Status": STATUS_LABEL[d.status], "Review": "⚠ check" if d.needs_review else "", "Why": d.reason})
        records.append({"student_id": r["student_id"], "status": d.status, "source": d.source, "confidence": d.confidence})
    return display, records
