"""Rule-based anomaly detection over attendance data (pure Python). Anomalies are FLAGS for a human to review: nothing here modifies a record.

Detectors (all thresholds are in `Thresholds` and can be tuned):
  DUPLICATE_RECORD        the same student has more than one record in one session (the database forbids it; this guards imports/bugs)
  CONCURRENT_ATTENDANCE   one student is marked present in two different subjects' sessions whose time spans overlap
  SESSION_RATE_OUTLIER    a session's attendance rate is far from the subject's usual rate (robust median/MAD z-score, unusual spike or drop)
  FLIP_FLOP               a student alternates present/absent almost every class (possible proxy attendance or unstable recognition)
  RECOGNITION_FAILURES    a large share of the faces/voices in a session were not recognised; REPEATED when it recurs across sessions
  CORRECTION_RATE         a teacher corrected an unusually large share of records
  CORRECTION_BURST        many corrections made within minutes
  LATE_CORRECTION         an ABSENT record changed to attended long after the session
  REPEAT_CORRECTION       the same student's record corrected again and again
These are heuristics: a flag means "look at this", not "something wrong happened"."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable, Mapping, Sequence

HIGH, WARN, INFO = "HIGH", "WARN", "INFO"
_ORDER = {HIGH: 0, WARN: 1, INFO: 2}
ATTENDED = frozenset({"PRESENT", "LATE"})


@dataclass(frozen=True)
class Thresholds:
    min_sessions_for_outlier: int = 6
    outlier_z: float = 3.5
    outlier_min_gap: float = 0.30            # also require the rate to differ by this much (rate 0..1), so tiny MAD does not over-flag
    flip_window: int = 8
    flip_min_changes: int = 6
    unknown_rate: float = 0.4
    min_faces: int = 5
    repeat_sessions: int = 3                 # of the last `repeat_window` sessions
    repeat_window: int = 5
    correction_rate: float = 0.15
    correction_min: int = 5
    burst_count: int = 5
    burst_minutes: int = 10
    late_correction_days: int = 7
    repeat_correction: int = 3


@dataclass(frozen=True)
class Anomaly:
    code: str
    severity: str
    message: str
    subject_id: int | None = None
    session_id: int | None = None
    student_id: int | None = None
    teacher_id: int | None = None
    evidence: Mapping = field(default_factory=dict)


def _sorted(items: list[Anomaly]) -> list[Anomaly]:
    return sorted(items, key=lambda a: (_ORDER[a.severity], a.code, a.subject_id or 0, a.session_id or 0, a.student_id or 0))


def duplicate_records(records: Iterable[Mapping]) -> list[Anomaly]:
    seen: dict[tuple[int, int], int] = defaultdict(int)
    for r in records:
        seen[(r["session_id"], r["student_id"])] += 1
    return [Anomaly("DUPLICATE_RECORD", HIGH, f"Student {sid} has {n} records in session {ses}.", session_id=ses, student_id=sid, evidence={"records": n})
            for (ses, sid), n in seen.items() if n > 1]


def concurrent_attendance(sessions: Sequence[Mapping], records: Iterable[Mapping]) -> list[Anomaly]:
    by_id = {s["session_id"]: s for s in sessions if s["status"] == "COMPLETED" and s.get("ended_at")}
    per_student: dict[int, list[Mapping]] = defaultdict(list)
    for r in records:
        if r["status"] in ATTENDED and r["session_id"] in by_id:
            per_student[r["student_id"]].append(by_id[r["session_id"]])
    out = []
    for sid, sess in per_student.items():
        sess = sorted(sess, key=lambda s: s["started_at"])
        for i, a in enumerate(sess):
            for b in sess[i + 1:]:
                if b["started_at"] >= a["ended_at"]:
                    break
                if a["subject_id"] != b["subject_id"]:
                    out.append(Anomaly("CONCURRENT_ATTENDANCE", HIGH,
                                       f"Student {sid} is marked present in two different subjects at the same time (sessions {a['session_id']} and {b['session_id']}).",
                                       subject_id=b["subject_id"], session_id=b["session_id"], student_id=sid,
                                       evidence={"sessions": [a["session_id"], b["session_id"]]}))
    return out


def session_rate_outliers(sessions: Sequence[Mapping], t: Thresholds = Thresholds()) -> list[Anomaly]:
    """sessions: completed-session summaries {session_id, subject_id, present, late, conducted}, any order."""
    by_subject: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for s in sessions:
        if s["conducted"]:
            by_subject[s["subject_id"]].append((s["session_id"], (s["present"] + s["late"]) / s["conducted"]))
    out = []
    for subj, rows in by_subject.items():
        if len(rows) < t.min_sessions_for_outlier:
            continue
        rates = [r for _, r in rows]
        med = median(rates)
        mad = median(abs(r - med) for r in rates)
        for sess, rate in rows:
            dev = abs(rate - med)
            z = 0.6745 * dev / mad if mad else (float("inf") if dev else 0.0)
            if dev >= t.outlier_min_gap and z >= t.outlier_z:
                kind = "spike" if rate > med else "drop"
                out.append(Anomaly("SESSION_RATE_OUTLIER", WARN, f"Attendance in session {sess} was {rate:.0%} against a usual {med:.0%} (unusual {kind}).",
                                   subject_id=subj, session_id=sess, evidence={"rate": round(rate, 3), "median": round(med, 3), "kind": kind}))
    return out


def flip_flops(histories: Mapping[tuple[int, int], Sequence[int]], t: Thresholds = Thresholds()) -> list[Anomaly]:
    """histories: {(subject_id, student_id): [0/1 oldest->newest]}."""
    out = []
    for (subj, sid), h in histories.items():
        w = list(h)[-t.flip_window:]
        if len(w) < t.flip_window:
            continue
        changes = sum(1 for a, b in zip(w, w[1:]) if a != b)
        if changes >= t.flip_min_changes:
            out.append(Anomaly("FLIP_FLOP", INFO, f"Student {sid} alternated between present and absent {changes} times in the last {len(w)} classes.",
                               subject_id=subj, student_id=sid, evidence={"changes": changes, "window": len(w)}))
    return out


def recognition_failures(sessions: Sequence[Mapping], t: Thresholds = Thresholds()) -> list[Anomaly]:
    """sessions carry `stats` = {faces, unknown, ambiguous, low_quality, ...} or None."""
    out, by_subject = [], defaultdict(list)
    for s in sorted(sessions, key=lambda s: s["started_at"]):
        st = s.get("stats") or {}
        total = st.get("faces") or st.get("segments") or 0
        if total < t.min_faces:
            continue
        bad = (st.get("unknown", 0) or 0) + (st.get("ambiguous", 0) or 0) + (st.get("low_quality", 0) or 0)
        rate = bad / total
        flagged = rate >= t.unknown_rate
        by_subject[s["subject_id"]].append(flagged)
        if flagged:
            out.append(Anomaly("RECOGNITION_FAILURES", WARN, f"{bad} of {total} detections in session {s['session_id']} were not recognised ({rate:.0%}).",
                               subject_id=s["subject_id"], session_id=s["session_id"], evidence={"rate": round(rate, 3), "total": total}))
    for subj, flags in by_subject.items():
        if sum(flags[-t.repeat_window:]) >= t.repeat_sessions:
            out.append(Anomaly("RECOGNITION_FAILURES", HIGH, f"Recognition failed repeatedly in this subject ({sum(flags[-t.repeat_window:])} of the last "
                               f"{min(len(flags), t.repeat_window)} sessions): check camera/lighting, enrolment photos, or whether people are being substituted.",
                               subject_id=subj, evidence={"repeated": True}))
    return out


def unusual_corrections(corrections: Sequence[Mapping], sessions: Sequence[Mapping], records: Sequence[Mapping], t: Thresholds = Thresholds()) -> list[Anomaly]:
    """corrections: {correction_id, record_id, session_id, student_id, subject_id, teacher_id, old_status, new_status, created_at, reverted_at}."""
    live = [c for c in corrections if not c.get("reverted_at")]
    out = []
    n_records: dict[int, int] = defaultdict(int)
    teacher_of = {s["session_id"]: s["teacher_id"] for s in sessions}
    for r in records:
        n_records[teacher_of.get(r["session_id"], -1)] += 1
    by_teacher: dict[int, list[Mapping]] = defaultdict(list)
    for c in live:
        by_teacher[c["teacher_id"]].append(c)
    for tid, cs in by_teacher.items():
        total = n_records.get(tid, 0)
        if len(cs) >= t.correction_min and total and len(cs) / total >= t.correction_rate:
            out.append(Anomaly("CORRECTION_RATE", WARN, f"{len(cs)} of {total} attendance records ({len(cs) / total:.0%}) were manually corrected.",
                               teacher_id=tid, evidence={"corrections": len(cs), "records": total}))
        times = sorted(c["created_at"] for c in cs)
        window = timedelta(minutes=t.burst_minutes)
        for i in range(len(times)):
            j = i
            while j < len(times) and times[j] - times[i] <= window:
                j += 1
            if j - i >= t.burst_count:
                out.append(Anomaly("CORRECTION_BURST", WARN, f"{j - i} corrections were made within {t.burst_minutes} minutes.", teacher_id=tid,
                                   evidence={"count": j - i, "at": times[i].isoformat()}))
                break
    ended = {s["session_id"]: s.get("ended_at") for s in sessions}
    for c in live:
        end = ended.get(c["session_id"])
        if end and c["old_status"] == "ABSENT" and c["new_status"] in ATTENDED and c["created_at"] - end > timedelta(days=t.late_correction_days):
            days = (c["created_at"] - end).days
            out.append(Anomaly("LATE_CORRECTION", WARN, f"An absence was changed to {c['new_status'].lower()} {days} days after the session.",
                               subject_id=c.get("subject_id"), session_id=c["session_id"], student_id=c["student_id"], teacher_id=c["teacher_id"], evidence={"days": days}))
    per_student: dict[tuple[int, int], int] = defaultdict(int)
    for c in live:
        per_student[(c.get("subject_id") or 0, c["student_id"])] += 1
    for (subj, sid), n in per_student.items():
        if n >= t.repeat_correction:
            out.append(Anomaly("REPEAT_CORRECTION", INFO, f"Student {sid}'s attendance was corrected {n} times in this subject.", subject_id=subj or None, student_id=sid,
                               evidence={"corrections": n}))
    return out


def detect(sessions: Sequence[Mapping], records: Sequence[Mapping], corrections: Sequence[Mapping] = (), t: Thresholds = Thresholds()) -> list[Anomaly]:
    """Run every detector. sessions: completed + others as fetched (need session_id, subject_id, teacher_id, status, started_at, ended_at,
    present/late/conducted, stats); records: {session_id, student_id, status}."""
    completed = [s for s in sessions if s["status"] == "COMPLETED"]
    histories: dict[tuple[int, int], list[int]] = defaultdict(list)
    subj_of = {s["session_id"]: s["subject_id"] for s in completed}
    start_of = {s["session_id"]: s["started_at"] for s in completed}
    for r in sorted((r for r in records if r["session_id"] in subj_of), key=lambda r: (start_of[r["session_id"]], r["session_id"])):
        if r["status"] in ATTENDED or r["status"] == "ABSENT":
            histories[(subj_of[r["session_id"]], r["student_id"])].append(1 if r["status"] in ATTENDED else 0)
    found = (duplicate_records(records) + concurrent_attendance(completed, records) + session_rate_outliers(completed, t)
             + flip_flops(histories, t) + recognition_failures(completed, t) + unusual_corrections(corrections, completed, records, t))
    return _sorted(found)
