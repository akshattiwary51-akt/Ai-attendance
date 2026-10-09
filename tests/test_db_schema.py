"""Real-PostgreSQL tests of schema, DB functions and Row Level Security (migrations 0001 + 0002).

  TEST_DATABASE_URL=postgresql://postgres:pw@localhost/postgres pytest tests/test_db_schema.py

Supabase's `auth` schema is simulated (auth.users + auth.uid() reading request.jwt.claims, as PostgREST sets it).
Skipped when TEST_DATABASE_URL is unset."""
import json
import os
import pathlib
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql  # noqa: E402

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")
MIGRATIONS = sorted((pathlib.Path(__file__).resolve().parents[1] / "supabase" / "migrations").glob("*.sql"))
TABLES = ["audit_logs", "attendance_corrections", "attendance_records", "attendance_sessions", "enrollments",
          "subjects", "voice_profiles", "face_profiles", "profiles", "students", "teachers"]

AUTH_SHIM = """
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key default gen_random_uuid(), email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
"""
USERS = ["t1", "t2", "tpend", "s1", "s2", "s3", "s4", "admin"]
UID = {name: str(uuid.uuid5(uuid.NAMESPACE_DNS, name)) for name in USERS}


@pytest.fixture(scope="module")
def dsn():
    admin = psycopg2.connect(URL); admin.autocommit = True
    cur = admin.cursor()
    for role, extra in (("anon", ""), ("authenticated", ""), ("service_role", "bypassrls")):
        cur.execute(f"do $$ begin create role {role} nologin {extra}; exception when duplicate_object then null; end $$")
    name = f"snap_{uuid.uuid4().hex[:8]}"
    cur.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    test_dsn = f"{URL.rsplit('/', 1)[0]}/{name}"
    c = psycopg2.connect(test_dsn); c.autocommit = True
    c.cursor().execute(AUTH_SHIM)
    for m in MIGRATIONS:
        c.cursor().execute(m.read_text())
    c.close()
    yield test_dsn
    cur.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))
    admin.close()


@pytest.fixture
def db(dsn):
    conn = psycopg2.connect(dsn); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("truncate " + ", ".join(TABLES) + " restart identity cascade; truncate auth.users cascade")
    yield cur
    cur.execute("reset role")
    conn.close()


def _ctx(cur, who):
    cur.execute("reset role")
    if who is None:
        cur.execute("select set_config('request.jwt.claims', '', false)"); cur.execute("set role anon")
    elif who == "service":
        cur.execute("set role service_role")
    elif who == "super":
        pass
    else:
        cur.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps({"sub": UID[who], "role": "authenticated"}),))
        cur.execute("set role authenticated")


def run(cur, who, q, *a):
    _ctx(cur, who)
    try:
        cur.execute(q, a)
        return cur.fetchall() if cur.description else None
    finally:
        cur.execute("reset role")


def one(cur, who, q, *a):
    return run(cur, who, q, *a)[0][0]


def code(cur, who, q, *a):
    """Statement must fail; return its SQLSTATE."""
    with pytest.raises(psycopg2.Error) as ei:
        run(cur, who, q, *a)
    return ei.value.pgcode


def count(cur, who, table):
    return one(cur, who, f"select count(*) from {table}")


def emb(n=128, v=0.1):
    return json.dumps([v] * n)


@pytest.fixture
def world(db):
    """t1/t2 active teachers, tpend inactive teacher, students s1-s3 enrolled in t1's DSA1, s4 outsider, one admin."""
    for u in USERS:
        run(db, "super", "insert into auth.users(id, email) values (%s, %s)", UID[u], f"{u}@x.com")
    run(db, "super", "select provision_account(%s,'ADMIN','Root','admin@x.com')", UID["admin"])
    for u in ("t1", "t2"):
        run(db, "super", "select provision_account(%s,'TEACHER',%s,%s,true)", UID[u], u.upper(), f"{u}@x.com")
    run(db, "super", "select provision_account(%s,'TEACHER','Pending','tpend@x.com',false)", UID["tpend"])
    for i, u in enumerate(("s1", "s2", "s3", "s4"), 1):
        run(db, "super", "select provision_account(%s,'STUDENT',%s,%s,true,%s,%s,%s)", UID[u], u.upper(), f"{u}@x.com", f"R{i}", emb(128, i / 10), emb(256, i / 10) if u != "s3" else None)
    run(db, "super", "insert into subjects(subject_code,name,section,teacher_id) values ('DSA1','DSA','A',1), ('OS1','OS','B',2)")
    for s in (1, 2, 3):
        run(db, "super", "insert into enrollments(student_id, subject_id) values (%s,1)", s)
    run(db, "super", "insert into enrollments(student_id, subject_id) values (4,2)")       # s4 belongs to t2's OS1
    return db


def new_session(db, who="t1", subject=1, method="FACE"):
    return one(db, who, "select create_attendance_session(%s,%s)", subject, method)


def recs(*rows):
    return json.dumps([{"student_id": s, "status": st, "source": "Photo 1"} for s, st in rows])


# ═════════ schema constraints ═════════
def test_duplicate_enrollment_rejected(world):
    assert code(world, "super", "insert into enrollments(student_id, subject_id) values (1,1)") == "23505"


def test_subject_code_unique_case_insensitive(world):
    assert code(world, "super", "insert into subjects(subject_code,name,section,teacher_id) values ('dsa1','x','B',2)") == "23505"


def test_unique_emails_and_roll_numbers_case_insensitive(world):
    assert code(world, "super", "insert into teachers(name,email) values ('x','T1@X.com')") == "23505"
    assert code(world, "super", "insert into students(name,email) values ('x','S1@x.COM')") == "23505"
    assert code(world, "super", "insert into students(name,roll_number) values ('x','r1')") == "23505"


def test_profile_role_linkage_is_enforced(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u)
    assert code(world, "super", "insert into profiles(user_id, role) values (%s,'TEACHER')", u) == "23514"
    assert code(world, "super", "insert into profiles(user_id, role, teacher_id, student_id) values (%s,'STUDENT',1,1)", u) == "23514"
    assert code(world, "super", "insert into profiles(user_id, role, student_id) values (%s,'STUDENT',1)", u) == "23505"   # student 1 already linked


def test_multiple_face_samples_but_single_active_voice(world):
    for _ in range(3):
        run(world, "super", "insert into face_profiles(student_id, embedding) values (1, %s)", emb())
    assert count(world, "super", "face_profiles where student_id=1") == 4
    assert code(world, "super", "insert into voice_profiles(student_id, embedding) values (1, %s)", emb(256)) == "23505"
    assert code(world, "super", "insert into face_profiles(student_id, embedding) values (1, '[1,2]')") == "23514"


def test_one_open_session_per_subject_even_bypassing_the_function(world):
    new_session(world)
    assert code(world, "t1", "select create_attendance_session(1,'FACE')") == "PT409"
    assert code(world, "super", "insert into attendance_sessions(subject_id,teacher_id,method,created_by) values (1,1,'FACE',1)") == "23505"


def test_session_invariants(world):
    assert code(world, "super", "insert into attendance_sessions(subject_id,teacher_id,method,status,created_by) values (1,1,'FACE','COMPLETED',1)") == "23514"
    assert code(world, "super", "insert into attendance_sessions(subject_id,teacher_id,method,created_by) values (1,1,'TELEPATHY',1)") == "23514"


# ═════════ session workflow (identity comes from auth.uid(), never a parameter) ═════════
def test_only_the_owning_active_teacher_can_create_a_session(world):
    assert code(world, "t2", "select create_attendance_session(1,'FACE')") == "PT403"        # someone else's subject
    assert code(world, "s1", "select create_attendance_session(1,'FACE')") == "PT403"        # a student
    assert code(world, "admin", "select create_attendance_session(1,'FACE')") == "PT403"
    assert code(world, "tpend", "select create_attendance_session(1,'FACE')") == "PT403"     # inactive teacher
    assert code(world, None, "select create_attendance_session(1,'FACE')") == "42501"        # anonymous
    assert code(world, "t1", "select create_attendance_session(99,'FACE')") == "PT404"
    assert count(world, "super", "attendance_sessions") == 0


def test_complete_session_saves_once_and_is_idempotent(world):
    sid = new_session(world)
    payload = recs((1, "PRESENT"), (2, "ABSENT"), (3, "ABSENT"), (1, "PRESENT"))
    assert one(world, "t1", "select complete_attendance_session(%s,%s)", sid, payload) == 3
    assert code(world, "t1", "select complete_attendance_session(%s,%s)", sid, payload) == "PT409"
    assert count(world, "super", "attendance_records") == 3
    assert one(world, "super", "select status from attendance_sessions where session_id=%s", sid) == "COMPLETED"


def test_complete_rejects_foreign_teacher_unenrolled_student_and_bad_status(world):
    sid = new_session(world)
    assert code(world, "t2", "select complete_attendance_session(%s,%s)", sid, recs((1, "PRESENT"))) == "PT403"
    assert code(world, "t1", "select complete_attendance_session(%s,%s)", sid, recs((4, "PRESENT"))) == "PT422"   # s4 not in DSA1
    assert code(world, "t1", "select complete_attendance_session(%s,%s)", sid, recs((1, "MAYBE"))) == "23514"
    assert count(world, "super", "attendance_records") == 0
    assert one(world, "super", "select status from attendance_sessions where session_id=%s", sid) == "OPEN"


def test_cancel_and_reopen_rules(world):
    sid = new_session(world)
    assert code(world, "t2", "select cancel_attendance_session(%s)", sid) == "PT403"
    run(world, "t1", "select cancel_attendance_session(%s)", sid)
    assert code(world, "t1", "select complete_attendance_session(%s,'[]')", sid) == "PT409"
    s2 = new_session(world)
    run(world, "t1", "select complete_attendance_session(%s,%s)", s2, recs((1, "PRESENT")))
    assert code(world, "t2", "select reopen_attendance_session(%s)", s2) == "PT403"
    run(world, "t1", "select reopen_attendance_session(%s)", s2)
    assert code(world, "t1", "select reopen_attendance_session(%s)", s2) == "PT409"
    run(world, "t1", "select complete_attendance_session(%s,%s)", s2, recs((1, "PRESENT"), (2, "ABSENT")))
    assert count(world, "super", "attendance_records") == 2
    s3 = new_session(world)
    assert code(world, "t1", "select reopen_attendance_session(%s)", s2) == "PT409"          # another is open


@pytest.fixture
def done(world):
    sid = new_session(world)
    run(world, "t1", "select complete_attendance_session(%s,%s)", sid, recs((1, "PRESENT"), (2, "ABSENT"), (3, "ABSENT")))
    return world, sid


def status(db, sid, stu):
    return one(db, "super", "select status from attendance_records where session_id=%s and student_id=%s", sid, stu)


def test_correction_updates_record_with_correction_and_audit(done):
    db, sid = done
    cid = one(db, "t1", "select correct_attendance_record(%s,2,'LATE','arrived 10 min late')", sid)
    assert status(db, sid, 2) == "LATE"
    assert run(db, "super", "select old_status,new_status,reason,corrected_by from attendance_corrections where correction_id=%s", cid)[0] == ("ABSENT", "LATE", "arrived 10 min late", 1)
    actor = run(db, "super", "select actor_role, actor_id, actor_user_id::text from audit_logs where action='attendance.corrected'")[0]
    assert actor == ("TEACHER", 1, UID["t1"])                                                 # who did it, taken from the JWT


def test_correction_validation_and_ownership(done):
    db, sid = done
    assert code(db, "t1", "select correct_attendance_record(%s,2,'LATE','  ')", sid) == "PT422"
    assert code(db, "t1", "select correct_attendance_record(%s,2,'ABSENT','same')", sid) == "PT422"
    assert code(db, "t1", "select correct_attendance_record(%s,2,'UNKNOWN','x')", sid) == "PT422"
    assert code(db, "t2", "select correct_attendance_record(%s,2,'LATE','x')", sid) == "PT403"
    assert code(db, "s2", "select correct_attendance_record(%s,2,'PRESENT','my own record')", sid) == "PT403"   # students cannot edit
    assert code(db, "t1", "select correct_attendance_record(%s,4,'LATE','x')", sid) == "PT404"
    assert count(db, "super", "attendance_corrections") == 0


def test_undo_restores_and_only_latest_can_be_undone(done):
    db, sid = done
    c1 = one(db, "t1", "select correct_attendance_record(%s,2,'LATE','r1')", sid)
    c2 = one(db, "t1", "select correct_attendance_record(%s,2,'EXCUSED','r2')", sid)
    assert code(db, "t1", "select undo_attendance_correction(%s)", c1) == "PT409"
    assert code(db, "t2", "select undo_attendance_correction(%s)", c2) == "PT403"
    run(db, "t1", "select undo_attendance_correction(%s)", c2)
    assert status(db, sid, 2) == "LATE"
    run(db, "t1", "select undo_attendance_correction(%s)", c1)
    assert status(db, sid, 2) == "ABSENT"
    assert not one(db, "super", "select manually_corrected from attendance_records where session_id=%s and student_id=2", sid)


def test_audit_log_is_append_only_even_for_superuser(done):
    db, _ = done
    assert code(db, "super", "update audit_logs set action='x'") == "PT403"
    assert code(db, "super", "delete from audit_logs") == "PT403"


# ═════════ Row Level Security matrix ═════════
TABLES_READ = ["students", "teachers", "subjects", "enrollments", "attendance_sessions", "attendance_records",
               "attendance_corrections", "face_profiles", "voice_profiles", "profiles", "audit_logs"]


@pytest.mark.parametrize("table", TABLES_READ)
def test_anonymous_can_read_nothing(world, table):
    assert code(world, None, f"select * from {table}") == "42501"


def test_anonymous_cannot_call_any_function(world):
    for q in ("select preview_subject('DSA1')", "select enroll_by_code('DSA1')", "select admin_set_active('TEACHER',1,false)",
              "select provision_account(gen_random_uuid(),'ADMIN','x','x@x')"):
        assert code(world, None, q) == "42501", q


@pytest.fixture
def attended(world):
    """One completed DSA1 session: s1 present, s2 absent, s3 absent; and an OS1 session for s4."""
    sid = new_session(world)
    run(world, "t1", "select complete_attendance_session(%s,%s)", sid, recs((1, "PRESENT"), (2, "ABSENT"), (3, "ABSENT")))
    os_sid = new_session(world, "t2", 2)
    run(world, "t2", "select complete_attendance_session(%s,%s)", os_sid, recs((4, "PRESENT")))
    return world, sid, os_sid


def test_student_sees_only_their_own_data(attended):
    db, sid, os_sid = attended
    assert [r[0] for r in run(db, "s1", "select name from students")] == ["S1"]
    assert [r[0] for r in run(db, "s1", "select student_id from attendance_records")] == [1]            # not s2/s3/s4
    assert [r[0] for r in run(db, "s1", "select subject_code from subjects")] == ["DSA1"]                # not OS1
    assert [r[0] for r in run(db, "s1", "select session_id from attendance_sessions")] == [sid]
    for t in ("teachers", "face_profiles", "voice_profiles", "attendance_corrections", "audit_logs"):
        assert count(db, "s1", t) == 0, t                                                                 # incl. own biometrics
    assert [r[0] for r in run(db, "s1", "select student_id from enrollments")] == [1]
    assert one(db, "s1", "select count(*) from profiles") == 1


def test_student_cannot_read_a_classmates_attendance_even_with_a_direct_filter(attended):
    db, *_ = attended
    assert run(db, "s1", "select * from attendance_records where student_id = 2") == []
    assert run(db, "s1", "select * from students where student_id = 2") == []
    assert run(db, "s4", "select * from attendance_records where student_id = 1") == []


def test_student_cannot_write_directly(attended):
    db, sid, _ = attended
    for q in ("update attendance_records set status='PRESENT' where student_id=1",
              "insert into attendance_records(session_id,student_id,status) values (1,1,'PRESENT')",
              "delete from attendance_records", "update students set is_active=false", "delete from face_profiles",
              "insert into attendance_sessions(subject_id,teacher_id,method,created_by) values (1,1,'FACE',1)",
              "update profiles set role='ADMIN'", "delete from subjects", "insert into audit_logs(actor_role,action,entity_type) values ('x','x','x')"):
        assert code(db, "s1", q) == "42501", q


def test_student_cannot_insert_a_subject_but_teacher_can_only_for_self(world):
    assert code(world, "s1", "insert into subjects(subject_code,name,section,teacher_id) values ('HACK','x','y',1)") == "42501"
    run(world, "t1", "insert into subjects(subject_code,name,section,teacher_id) values ('NEW1','n','s',1)")
    assert code(world, "t1", "insert into subjects(subject_code,name,section,teacher_id) values ('NEW2','n','s',2)") == "42501"   # RLS violation
    assert code(world, "tpend", "insert into subjects(subject_code,name,section,teacher_id) values ('NEW3','n','s',3)") == "42501"


def test_teacher_sees_only_own_subjects_students_sessions_and_biometrics(attended):
    db, sid, os_sid = attended
    assert [r[0] for r in run(db, "t1", "select subject_code from subjects")] == ["DSA1"]
    assert sorted(r[0] for r in run(db, "t1", "select name from students")) == ["S1", "S2", "S3"]        # not s4 / not t2's class
    assert [r[0] for r in run(db, "t1", "select session_id from attendance_sessions")] == [sid]
    assert sorted(r[0] for r in run(db, "t1", "select student_id from attendance_records")) == [1, 2, 3]
    assert sorted({r[0] for r in run(db, "t1", "select student_id from face_profiles")}) == [1, 2, 3]   # needed for recognition
    assert [r[0] for r in run(db, "t1", "select student_id from enrollments")] == [1, 2, 3]
    assert [r[0] for r in run(db, "t2", "select subject_code from subjects")] == ["OS1"]
    assert [r[0] for r in run(db, "t2", "select name from students")] == ["S4"]
    assert count(db, "t1", "teachers") == 1 and count(db, "t1", "audit_logs") == 0


def test_teacher_cannot_write_other_tables_directly(attended):
    db, *_ = attended
    for q in ("update attendance_records set status='PRESENT'", "delete from attendance_sessions", "update students set name='x'",
              "delete from face_profiles", "insert into enrollments(student_id,subject_id) values (4,1)", "update teachers set is_active=false"):
        assert code(db, "t1", q) == "42501", q


def test_teacher_can_remove_a_student_from_own_subject_only(attended):
    db, *_ = attended
    run(db, "t2", "delete from enrollments where subject_id = 1")                                       # not t2's class → no-op
    assert count(db, "super", "enrollments where subject_id=1") == 3
    run(db, "t1", "delete from enrollments where student_id=3 and subject_id=1")
    assert count(db, "super", "enrollments where subject_id=1") == 2
    run(db, "s1", "delete from enrollments")                                                           # a student can leave own subjects only
    assert count(db, "super", "enrollments") == 2                                                      # s1's DSA1 gone; s2 + s4 remain


def test_deactivated_user_loses_all_access_but_can_read_own_profile(world):
    run(world, "admin", "select admin_set_active('TEACHER',1,false)")
    assert count(world, "t1", "subjects") == 0 and count(world, "t1", "students") == 0
    assert code(world, "t1", "select create_attendance_session(1,'FACE')") == "PT403"
    assert run(world, "t1", "select is_active from profiles") == [(False,)]                            # app can show "account disabled"
    run(world, "admin", "select admin_set_active('TEACHER',1,true)")
    assert count(world, "t1", "subjects") == 1


def test_admin_sees_everything_and_manages_activation(attended):
    db, *_ = attended
    assert count(db, "admin", "students") == 4 and count(db, "admin", "teachers") == 3
    assert count(db, "admin", "attendance_records") == 4 and count(db, "admin", "audit_logs") >= 6
    assert count(db, "admin", "face_profiles") == 0                                                    # admin does NOT get biometrics
    assert code(db, "t1", "select admin_set_active('TEACHER',3,true)") == "PT403"
    assert code(db, "s1", "select admin_set_active('STUDENT',1,false)") == "PT403"
    run(db, "admin", "select admin_set_active('TEACHER',3,true)")                                      # approve the pending teacher
    assert one(db, "super", "select is_active from teachers where teacher_id=3") and one(db, "super", "select is_active from profiles where teacher_id=3")
    assert run(db, "super", "select actor_role from audit_logs where action='user.activated'") == [("ADMIN",)]
    assert code(db, "admin", "select admin_set_active('ADMIN',1,true)") == "PT422"
    assert code(db, "admin", "select admin_set_active('TEACHER',999,true)") == "PT404"
    assert code(db, "admin", "update attendance_records set status='PRESENT'") == "42501"              # even admins can't bypass the audited path


# ═════════ enrolment by code ═════════
def test_enroll_by_code_is_student_only_idempotent_and_case_insensitive(world):
    assert code(world, "t1", "select enroll_by_code('OS1')") == "PT403"
    assert one(world, "s1", "select enroll_by_code(' os1 ')") ["outcome"] == "ENROLLED"
    assert one(world, "s1", "select enroll_by_code('OS1')")["outcome"] == "ALREADY_ENROLLED"
    assert one(world, "s1", "select enroll_by_code('NOPE')") == {"outcome": "NOT_FOUND"}
    assert count(world, "super", "enrollments where student_id=1 and subject_id=2") == 1
    assert [r[0] for r in run(world, "s1", "select subject_code from subjects order by 1")] == ["DSA1", "OS1"]


def test_preview_subject_does_not_leak_ids_of_other_data(world):
    p = one(world, "s4", "select preview_subject('DSA1')")
    assert p["name"] == "DSA" and p["enrolled"] is False and set(p) == {"subject_id", "name", "section", "enrolled"}
    assert one(world, "s1", "select preview_subject('dsa1')")["enrolled"] is True
    assert one(world, "s1", "select preview_subject('NOPE')") is None


# ═════════ provisioning ═════════
def test_provision_is_service_role_only(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u)
    for who in ("s1", "t1", "admin"):
        assert code(world, who, "select provision_account(%s,'ADMIN','x','x@x')", u) == "42501", who
    run(world, "service", "select provision_account(%s,'STUDENT','New Kid','new@x.com',true,'R99',%s,null)", u, emb())
    assert run(world, "super", "select role, is_active from profiles where user_id=%s", u) == [("STUDENT", True)]
    assert count(world, "super", "face_profiles where student_id = (select student_id from profiles where user_id='%s')" % u) == 1


def test_provision_is_atomic_and_validates(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u)
    before = count(world, "super", "students")
    assert code(world, "service", "select provision_account(%s,'STUDENT','Bad','bad@x.com',true,null,'[1,2]')", u) == "23514"
    assert count(world, "super", "students") == before and count(world, "super", "profiles where user_id='%s'" % u) == 0   # no orphan rows
    assert code(world, "service", "select provision_account(%s,'STUDENT','  ','b@x.com')", u) == "PT422"
    assert code(world, "service", "select provision_account(%s,'STUDENT','Dup','s1@x.com')", u) == "23505"            # email taken
    assert code(world, "service", "select provision_account(%s,'WIZARD','x','x@x')", u) == "PT422"


def test_new_teacher_can_start_pending(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u)
    tid = one(world, "service", "select provision_account(%s,'TEACHER','New T','nt@x.com',false)", u)
    assert run(world, "super", "select is_active from teachers where teacher_id=%s", tid) == [(False,)]
