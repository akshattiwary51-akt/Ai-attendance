from datetime import datetime, timedelta, timezone

from src.analytics import anomalies as an

T0 = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)


def sess(i, subject=1, teacher=1, day=0, minutes=50, present=8, absent=2, status="COMPLETED", stats=None, hour=0):
    start = T0 + timedelta(days=day, hours=hour)
    return {"session_id": i, "subject_id": subject, "teacher_id": teacher, "status": status, "started_at": start,
            "ended_at": start + timedelta(minutes=minutes), "present": present, "late": 0, "absent": absent, "conducted": present + absent, "stats": stats}


def codes(found): return [a.code for a in found]


def test_clean_data_has_no_anomalies():
    sessions = [sess(i, day=i, present=8 + (i % 2)) for i in range(1, 9)]
    recs = [{"session_id": i, "student_id": s, "status": "PRESENT" if (i + s) % 5 else "ABSENT"} for i in range(1, 9) for s in range(1, 5)]
    assert an.detect(sessions, recs) == []


def test_duplicate_records():
    f = an.duplicate_records([{"session_id": 1, "student_id": 5}, {"session_id": 1, "student_id": 5}, {"session_id": 1, "student_id": 6}])
    assert codes(f) == ["DUPLICATE_RECORD"] and f[0].severity == an.HIGH and f[0].student_id == 5


def test_concurrent_attendance_only_for_overlapping_different_subjects():
    sessions = [sess(1, subject=1, hour=0), sess(2, subject=2, hour=0, minutes=30), sess(3, subject=3, hour=2), sess(4, subject=1, hour=0, day=1)]
    recs = [{"session_id": i, "student_id": 9, "status": "PRESENT"} for i in (1, 2, 3)] + [{"session_id": 1, "student_id": 8, "status": "PRESENT"},
            {"session_id": 2, "student_id": 8, "status": "ABSENT"}]
    f = an.concurrent_attendance(sessions, recs)
    assert [(a.student_id, a.evidence["sessions"]) for a in f] == [(9, [1, 2])]                 # sessions 1 and 3 do not overlap; student 8 was absent in 2


def test_same_subject_overlap_is_not_flagged():
    sessions = [sess(1, subject=1), sess(2, subject=1, minutes=40)]
    assert an.concurrent_attendance(sessions, [{"session_id": i, "student_id": 1, "status": "PRESENT"} for i in (1, 2)]) == []


def test_session_rate_outlier_spike_and_drop_but_not_small_variation():
    base = [sess(i, day=i, present=7, absent=3) for i in range(1, 8)]
    spike, drop = sess(20, day=20, present=10, absent=0), sess(21, day=21, present=2, absent=8)
    f = an.session_rate_outliers(base + [spike, drop])
    assert {(a.session_id, a.evidence["kind"]) for a in f} == {(20, "spike"), (21, "drop")}
    assert an.session_rate_outliers(base + [sess(22, day=22, present=8, absent=2)]) == []   # 80% vs 70%: ordinary variation
    assert an.session_rate_outliers(base[:3] + [spike]) == []                               # too little history to judge


def test_flip_flop_needs_a_full_alternating_window():
    f = an.flip_flops({(1, 5): [1, 0, 1, 0, 1, 0, 1, 0], (1, 6): [1, 1, 0, 0, 1, 1, 0, 0], (1, 7): [1, 0, 1, 0]})
    assert [(a.student_id, a.severity) for a in f] == [(5, an.INFO)]


def test_recognition_failures_single_and_repeated():
    bad = {"faces": 10, "unknown": 3, "ambiguous": 1, "low_quality": 1}
    good = {"faces": 10, "unknown": 0}
    sessions = [sess(1, day=1, stats=good), sess(2, day=2, stats=bad), sess(3, day=3, stats=bad), sess(4, day=4, stats=bad), sess(5, day=5, stats={"faces": 2, "unknown": 2})]
    f = an.recognition_failures(sessions)
    assert sum(a.severity == an.WARN for a in f) == 3 and sum(a.severity == an.HIGH and a.evidence.get("repeated") for a in f) == 1
    assert an.recognition_failures([sess(1, stats=bad)])[0].severity == an.WARN                  # a single bad session is only a warning
    assert an.recognition_failures([sess(1, stats=None)]) == []


def corr(i, minutes=0, student=1, old="ABSENT", new="PRESENT", teacher=1, session=1, reverted=None, days=0):
    return {"correction_id": i, "record_id": i, "session_id": session, "student_id": student, "subject_id": 1, "teacher_id": teacher,
            "old_status": old, "new_status": new, "created_at": T0 + timedelta(days=days, minutes=minutes), "reverted_at": reverted}


def test_corrections_rate_burst_late_and_repeat():
    sessions = [sess(1)]
    records = [{"session_id": 1, "student_id": s, "status": "PRESENT"} for s in range(1, 21)]
    many = [corr(i, minutes=i, student=i) for i in range(1, 7)]                                   # 6 of 20 = 30%, all within 6 minutes
    f = an.unusual_corrections(many, sessions, records)
    assert {"CORRECTION_RATE", "CORRECTION_BURST"} <= set(codes(f)) and "LATE_CORRECTION" not in codes(f)
    late = an.unusual_corrections([corr(1, days=30)], sessions, records)
    assert codes(late) == ["LATE_CORRECTION"] and late[0].evidence["days"] >= 29
    rep = an.unusual_corrections([corr(i, student=5, minutes=i * 60) for i in range(1, 4)], sessions, records)
    assert "REPEAT_CORRECTION" in codes(rep)


def test_reverted_corrections_and_other_directions_do_not_count():
    sessions, records = [sess(1)], [{"session_id": 1, "student_id": s, "status": "PRESENT"} for s in range(1, 21)]
    assert an.unusual_corrections([corr(i, minutes=i, student=i, reverted=T0) for i in range(1, 8)], sessions, records) == []
    assert an.unusual_corrections([corr(1, days=30, old="PRESENT", new="ABSENT")], sessions, records) == []      # removing attendance late is not flagged here


def test_detect_runs_everything_and_sorts_by_severity():
    sessions = [sess(1, subject=1, hour=0), sess(2, subject=2, hour=0, minutes=30)]
    records = [{"session_id": 1, "student_id": 1, "status": "PRESENT"}, {"session_id": 2, "student_id": 1, "status": "PRESENT"}, {"session_id": 2, "student_id": 1, "status": "PRESENT"}]
    found = an.detect(sessions, records, [corr(1, student=1, session=2)])
    assert {"CONCURRENT_ATTENDANCE", "DUPLICATE_RECORD"} <= set(codes(found)) and [a.severity for a in found] == sorted([a.severity for a in found], key=lambda x: an._ORDER[x])


def test_detectors_do_not_mutate_inputs():
    sessions = [sess(i, day=i) for i in range(1, 8)]; records = [{"session_id": 1, "student_id": 1, "status": "PRESENT"}]
    import copy
    before = copy.deepcopy((sessions, records)); an.detect(sessions, records); assert (sessions, records) == before
