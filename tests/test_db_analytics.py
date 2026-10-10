"""Views / functions from migration 0003 on real PostgreSQL (needs TEST_DATABASE_URL)."""
import pytest

psycopg2 = pytest.importorskip("psycopg2")
from tests.db_support import (  # noqa: E402,F401
    code, count, db, dsn, emb, new_session, one, recs, requires_db, run, world,
)

pytestmark = requires_db


def complete(db, who, sid, *rows):
    run(db, who, "select complete_attendance_session(%s,%s)", sid, recs(*rows))


@pytest.fixture
def history(world):
    """DSA1 (t1): 3 completed sessions.  s1: P,P,A   s2: L,A,EXCUSED   s3: A,A,A.   OS1 (t2): 1 session, s4 present."""
    db = world
    for rows in ([(1, "PRESENT"), (2, "LATE"), (3, "ABSENT")],
                 [(1, "PRESENT"), (2, "ABSENT"), (3, "ABSENT")],
                 [(1, "ABSENT"), (2, "ABSENT"), (3, "ABSENT")]):
        complete(db, "t1", new_session(db), *rows)
    run(db, "t1", "select correct_attendance_record(%s,2,'EXCUSED','medical')", 3)
    complete(db, "t2", new_session(db, "t2", 2), (4, "PRESENT"))
    return db


def view(db, who, where=""):
    return run(db, who, f"select subject_id, student_id, attended, conducted, excused from v_subject_student_attendance {where} order by 1, 2")


def test_attendance_view_counts_follow_the_rules(history):
    assert view(history, "t1", "where subject_id = 1") == [(1, 1, 2, 3, 0), (1, 2, 1, 2, 1), (1, 3, 0, 3, 0)]


def test_only_completed_sessions_count(history):
    sid = new_session(history)
    run(history, "t1", "select cancel_attendance_session(%s)", sid)
    s2 = new_session(history)
    run(history, "t1", "select complete_attendance_session(%s,%s)", s2, recs((1, "PRESENT")))
    run(history, "t1", "select reopen_attendance_session(%s)", s2)
    assert view(history, "t1", "where subject_id = 1 and student_id = 1") == [(1, 1, 2, 3, 0)]


def test_view_respects_rls_for_every_role(history):
    assert [r[:2] for r in view(history, "s1")] == [(1, 1)]
    assert [r[:2] for r in view(history, "s4")] == [(2, 4)]
    assert [r[:2] for r in view(history, "t2")] == [(2, 4)]
    assert len(view(history, "t1")) == 3 and len(view(history, "admin")) == 4
    assert code(history, None, "select * from v_subject_student_attendance") == "42501"
    assert view(history, "tpend") == []
    assert view(history, "s2", "where student_id = 1") == []


def test_session_summary_is_teacher_and_admin_only(history):
    rows = run(history, "t1", "select session_id, present, late, absent, excused, conducted from v_session_summary order by 1")
    assert rows == [(1, 1, 1, 1, 0, 3), (2, 1, 0, 2, 0, 3), (3, 0, 0, 2, 1, 2)]
    assert [r[0] for r in run(history, "t2", "select session_id from v_session_summary")] == [4]
    assert len(run(history, "admin", "select 1 from v_session_summary")) == 4
    assert run(history, "s1", "select * from v_session_summary") == []
    assert code(history, None, "select * from v_session_summary") == "42501"


def test_session_summary_includes_open_sessions_with_zero_counts(world):
    new_session(world)
    assert run(world, "t1", "select present, conducted, status from v_session_summary") == [(0, 0, "OPEN")]


def test_target_default_and_owner_only_change_with_audit(world):
    assert one(world, "s1", "select target_percent from subjects where subject_id = 1") == 75
    run(world, "t1", "select set_subject_target(1, 80.5)")
    assert float(one(world, "s1", "select target_percent from subjects where subject_id = 1")) == 80.5
    assert code(world, "t2", "select set_subject_target(1, 60)") == "PT403"
    assert code(world, "s1", "select set_subject_target(1, 60)") == "PT403"
    assert code(world, "admin", "select set_subject_target(1, 60)") == "PT403"
    assert code(world, "t1", "select set_subject_target(1, 0)") == "PT422"
    assert code(world, "t1", "select set_subject_target(1, 101)") == "PT422"
    assert code(world, "t1", "select set_subject_target(99, 80)") == "PT404"
    assert code(world, None, "select set_subject_target(1, 80)") == "42501"
    assert code(world, "t1", "update subjects set target_percent = 1") == "42501"
    assert run(world, "super", "select details->>'from', details->>'to' from audit_logs where action='subject.target_changed'") == [("75.00", "80.5")]


def test_target_constraint_at_table_level(world):
    assert code(world, "super", "update subjects set target_percent = 0") == "23514"


def test_admin_overview_numbers_and_access(history):
    o = one(history, "admin", "select admin_overview('UTC')")
    assert o["teachers"] == 2 and o["pending_teachers"] == 1 and o["students"] == 4 and o["subjects"] == 2
    assert o["sessions_today"] == 4
    assert (o["attended"], o["conducted"]) == (4, 9)
    assert o["average_attendance"] == round(100 * 4 / 9, 1)
    for who in ("t1", "s1", "tpend"):
        assert code(history, who, "select admin_overview('UTC')") == "PT403"
    assert code(history, None, "select admin_overview('UTC')") == "42501"
    assert one(history, "admin", "select admin_overview('Not/AZone')")["sessions_today"] == 4


def test_admin_overview_with_no_attendance_has_null_average(world):
    o = one(world, "admin", "select admin_overview()")
    assert o["average_attendance"] is None and o["conducted"] == 0
