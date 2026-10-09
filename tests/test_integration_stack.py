"""services → repositories → PostgREST (JWT auth) → PostgreSQL (RLS), end to end, as real distinct users.

  TEST_POSTGREST_URL=http://localhost:3111  TEST_POSTGREST_DSN=postgresql://postgres:pw@localhost/snapclass_test
  TEST_JWT_SECRET=<PostgREST jwt-secret>      (recipe: docs/TESTING.md)
Supabase Auth itself is replaced by a provider that mints JWTs the same way GoTrue does (role=authenticated, sub=uid)."""
import os
import time
import uuid

import pytest

URL, DSN, SECRET = (os.environ.get(k) for k in ("TEST_POSTGREST_URL", "TEST_POSTGREST_DSN", "TEST_JWT_SECRET"))
pytestmark = pytest.mark.skipif(not (URL and DSN and SECRET), reason="integration env vars not set")
psycopg2 = pytest.importorskip("psycopg2")
jwt = pytest.importorskip("jwt")

from src.database import client  # noqa: E402
from src.repositories import attendance_repository, enrollment_repository, student_repository  # noqa: E402
from src.security.auth_provider import AuthSession, set_auth_provider  # noqa: E402
from src.security.principal import Principal, acting_as  # noqa: E402
from src.services import (  # noqa: E402
    admin_service, attendance_service as att, auth_service, enrollment_service, session_service, subject_service,
)
from src.services.attendance_service import Detection  # noqa: E402
from src.utils.errors import (  # noqa: E402
    AuthenticationError, AuthorizationError, ConflictError, NotFoundError, ValidationError,
)

TABLES = ("audit_logs, attendance_corrections, attendance_records, attendance_sessions, enrollments, subjects, "
          "voice_profiles, face_profiles, profiles, students, teachers")


def mint(user_id: str | None, role="authenticated", ttl=3600) -> str:
    claims = {"role": role, "exp": int(time.time()) + ttl}
    if user_id:
        claims["sub"] = user_id
    return jwt.encode(claims, SECRET, algorithm="HS256")


class PgAuthProvider:
    """Stand-in for Supabase Auth backed by auth.users, issuing real HS256 JWTs."""

    def __init__(self, cur):
        self.cur, self.users, self.deleted = cur, {}, []

    def sign_up(self, email, password):
        if email in self.users:
            raise ValidationError("exists", user_message="An account with this email already exists.")
        uid = str(uuid.uuid4())
        self.cur.execute("insert into auth.users(id, email) values (%s,%s)", (uid, email))
        self.users[email] = (uid, password)
        return uid

    create_confirmed_user = sign_up

    def sign_in(self, email, password):
        uid, pw = self.users.get(email, (None, None))
        if uid is None or pw != password:
            raise AuthenticationError("bad credentials")
        return AuthSession(uid, mint(uid), "refresh-" + uid, int(time.time()) + 3600)

    def refresh(self, refresh_token): raise NotImplementedError
    def sign_out(self, access_token): pass
    def delete_user(self, user_id): self.deleted.append(user_id)


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setattr(client, "build_user_client", lambda token: client.Db(URL, {"Authorization": f"Bearer {token}"}))
    monkeypatch.setattr(client, "build_admin_client", lambda: client.Db(URL, {"Authorization": f"Bearer {mint(None, 'service_role')}"}))
    monkeypatch.setenv("SUPABASE_URL", "http://unused"); monkeypatch.setenv("SUPABASE_ANON_KEY", "x")
    conn = psycopg2.connect(DSN); conn.autocommit = True
    cur = conn.cursor(); cur.execute(f"truncate {TABLES} restart identity cascade; truncate auth.users cascade")
    provider = PgAuthProvider(cur)
    set_auth_provider(provider)
    yield cur, provider
    set_auth_provider(None); conn.close()


def emb(seed, n=128):
    import random
    r = random.Random(seed); return [r.uniform(-1, 1) for _ in range(n)]


def as_(payload):
    a = payload["auth"]
    return acting_as(Principal(a["user_id"], a["access_token"], a["role"], a["teacher_id"], a["student_id"]))


PW = dict(password="correct-horse", confirm="correct-horse")


@pytest.fixture
def school(pg):
    """admin; approved teacher T1 with subject DSA1; teacher T2; students Asha/Bilal/Chen enrolled in DSA1; Dev in none."""
    cur, provider = pg
    from src.repositories import account_repository
    account_repository.provision(provider.create_confirmed_user("root@x.co", "root-password"), "ADMIN", "Root", "root@x.co")
    admin = auth_service.login("root@x.co", "root-password", "ADMIN")

    for email, name in (("t1@x.co", "Teacher One"), ("t2@x.co", "Teacher Two")):
        assert auth_service.register_teacher(email, name, **PW).pending_approval
    with as_(admin):
        for t in admin_service.pending_teachers():
            admin_service.set_active("TEACHER", t["teacher_id"], True)
    t1, t2 = (auth_service.login(e, PW["password"], "TEACHER") for e in ("t1@x.co", "t2@x.co"))
    with as_(t1):
        subject = subject_service.create_subject(t1["user"]["teacher_id"], "DSA1", "DSA", "A")
    students = {}
    for i, name in enumerate(["Asha", "Bilal", "Chen", "Dev"], 1):
        auth_service.register_student(f"{name.lower()}@x.co", name, PW["password"], PW["confirm"], f"R{i}", emb(i), emb(100 + i, 256) if i == 1 else None, True)
        students[name] = auth_service.login(f"{name.lower()}@x.co", PW["password"], "STUDENT")
    for name in ("Asha", "Bilal", "Chen"):
        with as_(students[name]):
            assert enrollment_service.enroll_by_code("dsa1")[0].value == "ENROLLED"
    return dict(admin=admin, t1=t1, t2=t2, students=students, subject_id=subject["subject_id"], cur=cur)


# ═════════ accounts, approval, roles ═════════
def test_teacher_cannot_login_until_admin_approves(pg):
    cur, provider = pg
    from src.repositories import account_repository
    account_repository.provision(provider.create_confirmed_user("root@x.co", "root-password"), "ADMIN", "Root", "root@x.co")
    auth_service.register_teacher("new@x.co", "New Teacher", **PW)
    with pytest.raises(AuthenticationError) as ei:
        auth_service.login("new@x.co", PW["password"], "TEACHER")
    assert "pending approval" in ei.value.user_message
    admin = auth_service.login("root@x.co", "root-password", "ADMIN")
    with as_(admin):
        (pending,) = admin_service.pending_teachers()
        admin_service.set_active("TEACHER", pending["teacher_id"], True)
        assert [a["action"] for a in admin_service.audit_log()][:2] == ["user.activated", "account.provisioned"]
    assert auth_service.login("new@x.co", PW["password"], "TEACHER")["user"]["name"] == "New Teacher"


def test_role_gates_at_login_and_in_the_database(school):
    for email, wrong_role in (("t1@x.co", "STUDENT"), ("asha@x.co", "TEACHER"), ("asha@x.co", "ADMIN"), ("root@x.co", "TEACHER")):
        with pytest.raises(AuthenticationError):
            auth_service.login(email, PW["password"] if email != "root@x.co" else "root-password", wrong_role)
    with as_(school["students"]["Asha"]):
        with pytest.raises(AuthorizationError):
            session_service.get_or_start(1, school["subject_id"], "FACE")
        with pytest.raises(AuthorizationError):
            admin_service.set_active("TEACHER", 1, False)
        assert admin_service.teachers() == [] and admin_service.audit_log() == []         # RLS: empty, not leaked
    with as_(school["t1"]):
        with pytest.raises(AuthorizationError):
            admin_service.set_active("TEACHER", 2, False)
        assert admin_service.audit_log() == []


def test_duplicate_email_registration_is_rejected_and_leaves_no_orphan(school, pg):
    cur, provider = pg
    with pytest.raises(ValidationError):
        auth_service.register_teacher("t1@x.co", "Imposter", **PW)       # same email already a teacher (auth user also exists)
    n_before = len(provider.deleted)
    auth_service.register_student("fresh@x.co", "Fresh", PW["password"], PW["confirm"], None, emb(55), None, True)
    # Same email for a different identity: auth.sign_up of a NEW address succeeds, provisioning rejects the duplicate roll number
    with pytest.raises(ValidationError):
        auth_service.register_student("fresh2@x.co", "Fresh2", PW["password"], PW["confirm"], "R1", emb(56), None, True)
    assert len(provider.deleted) == n_before + 1                         # the just-created auth user was removed again


def test_no_principal_and_garbage_or_expired_tokens_are_rejected(school):
    with pytest.raises(AuthenticationError):
        enrollment_service.student_subjects(1)                            # nobody logged in
    for token in (mint("00000000-0000-0000-0000-000000000000", ttl=-300), "not-a-jwt"):
        with acting_as(Principal("x", token)):
            with pytest.raises(AuthenticationError) as ei:
                enrollment_service.student_subjects(1)
            assert "expired" in ei.value.user_message.lower()


def test_forged_token_for_unknown_user_sees_nothing(school):
    with acting_as(Principal("ghost", mint(str(uuid.uuid4())))):          # validly signed, but no profile
        assert enrollment_service.student_subjects(1) == [] and student_repository.get_face_gallery([1, 2]) == {}
        with pytest.raises(AuthorizationError):
            session_service.get_or_start(1, school["subject_id"], "FACE")


# ═════════ data isolation ═════════
def test_students_only_see_their_own_subjects_and_attendance(school):
    t1, sid = school["t1"], school["subject_id"]
    asha, bilal, dev = (school["students"][n] for n in ("Asha", "Bilal", "Dev"))
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        s = session_service.get_or_start(t1["user"]["teacher_id"], sid, "FACE")
        _, records = att.build_attendance_rows(roster, {r["student_id"]: Detection(r["student_id"], "Photo 1") for r in roster if r["name"] == "Asha"})
        session_service.confirm(t1["user"]["teacher_id"], s["session_id"], records)
    with as_(asha):
        assert att.get_student_stats(asha["user"]["student_id"])[sid]["percentage"] == 100.0
        assert attendance_repository.list_for_student(bilal["user"]["student_id"]) == []     # direct attempt at a classmate
        assert enrollment_repository.subjects_of_student(bilal["user"]["student_id"]) == []
    with as_(bilal):
        assert att.get_student_stats(bilal["user"]["student_id"])[sid]["percentage"] == 0.0
    with as_(dev):                                                                           # not enrolled anywhere
        assert enrollment_service.student_subjects(dev["user"]["student_id"]) == []
        assert att.get_student_stats(dev["user"]["student_id"]) == {}
        assert attendance_repository.list_for_student(asha["user"]["student_id"]) == []


def test_teachers_are_isolated_from_each_other(school):
    t1, t2, sid = school["t1"], school["t2"], school["subject_id"]
    with as_(t1):
        s = session_service.get_or_start(t1["user"]["teacher_id"], sid, "FACE")
    with as_(t2):
        tid = t2["user"]["teacher_id"]
        assert subject_service.list_teacher_subjects(tid) == []
        assert enrollment_service.subject_roster(sid) == []
        assert session_service.list_sessions(tid).empty
        with pytest.raises((AuthorizationError, NotFoundError)):
            session_service.session_detail(tid, s["session_id"])
        with pytest.raises((AuthorizationError, NotFoundError)):
            session_service.confirm(tid, s["session_id"], [])
        with pytest.raises(AuthorizationError):
            session_service.get_or_start(tid, sid, "FACE")
        with pytest.raises(AuthorizationError):
            subject_service.create_subject(t1["user"]["teacher_id"], "STEAL1", "x", "y")      # insert as someone else


def test_biometric_templates_are_visible_only_to_the_teacher_of_that_student(school):
    ids = {n: school["students"][n]["user"]["student_id"] for n in school["students"]}
    with as_(school["t1"]):
        g = student_repository.get_face_gallery(list(ids.values()))
        assert set(g) == {ids["Asha"], ids["Bilal"], ids["Chen"]}                            # Dev isn't in T1's class
        assert set(student_repository.get_voice_gallery(list(ids.values()))) == {ids["Asha"]}
    for who in (school["t2"], school["admin"], school["students"]["Asha"], school["students"]["Dev"]):
        with as_(who):
            assert student_repository.get_face_gallery(list(ids.values())) == {}
            assert student_repository.get_voice_gallery(list(ids.values())) == {}


# ═════════ the attendance workflow, as the real teacher ═════════
def test_full_attendance_flow_with_corrections_and_student_stats(school):
    t1, sid = school["t1"], school["subject_id"]
    tid, chen = t1["user"]["teacher_id"], school["students"]["Chen"]["user"]["student_id"]
    cur = school["cur"]
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        assert [r["name"] for r in roster] == ["Asha", "Bilal", "Chen"]
        session = session_service.get_or_start(tid, sid, "FACE")
        assert session_service.get_or_start(tid, sid, "FACE")["session_id"] == session["session_id"]
        with pytest.raises(ConflictError):
            session_service.get_or_start(tid, sid, "VOICE")
        by_name = {r["name"]: r["student_id"] for r in roster}
        _, records = att.build_attendance_rows(roster, {by_name["Asha"]: Detection(by_name["Asha"], "Photo 1, Photo 2"),
                                                        by_name["Bilal"]: Detection(by_name["Bilal"], "Voice", 0.91)})
        assert session_service.confirm(tid, session["session_id"], records) == 3
        assert session_service.confirm(tid, session["session_id"], records) == 0

        cid = session_service.correct_record(tid, session["session_id"], chen, "LATE", "bus delay")
        detail = session_service.session_detail(tid, session["session_id"])
        assert {r["students"]["name"]: r["status"] for r in detail["records"]} == {"Asha": "PRESENT", "Bilal": "PRESENT", "Chen": "LATE"}
        assert [c["correction_id"] for c in session_service.undoable_corrections(detail["corrections"])] == [cid]
    with as_(school["students"]["Chen"]):
        assert att.get_student_stats(chen)[sid]["percentage"] == 100.0                        # LATE counts as attended
    with as_(t1):
        session_service.undo_correction(tid, cid)
        session_service.correct_record(tid, session["session_id"], chen, "EXCUSED", "medical")
    with as_(school["students"]["Chen"]):
        assert att.get_student_stats(chen).get(sid, {"total": 0})["total"] == 0               # excused is neutral
    cur.execute("select action, actor_role from audit_logs where action like 'attendance.%' or action like 'session.%' order by audit_id")
    assert cur.fetchall() == [("session.created", "TEACHER"), ("session.completed", "TEACHER"), ("attendance.corrected", "TEACHER"),
                              ("attendance.correction_undone", "TEACHER"), ("attendance.corrected", "TEACHER")]
    with as_(t1):
        assert list(session_service.list_sessions(tid)["Attendance"]) == ["✅ 2 / 2"]
        assert subject_service.list_teacher_subjects(tid)[0]["total_classes"] == 1


def test_discard_allows_a_new_session_and_students_never_see_cancelled_ones(school):
    t1, sid = school["t1"], school["subject_id"]; tid = t1["user"]["teacher_id"]
    with as_(t1):
        s1 = session_service.get_or_start(tid, sid, "FACE")
        session_service.discard(tid, s1["session_id"]); session_service.discard(tid, s1["session_id"])
        assert session_service.get_or_start(tid, sid, "VOICE")["session_id"] != s1["session_id"]
    with as_(school["students"]["Asha"]):
        assert att.get_student_stats(school["students"]["Asha"]["user"]["student_id"]) == {}


def test_unenrolled_student_cannot_be_recorded(school):
    t1, sid = school["t1"], school["subject_id"]; tid = t1["user"]["teacher_id"]
    dev = school["students"]["Dev"]["user"]["student_id"]
    with as_(t1):
        s = session_service.get_or_start(tid, sid, "FACE")
        with pytest.raises(ValidationError):
            session_service.confirm(tid, s["session_id"], [{"student_id": dev, "status": "PRESENT", "source": None, "confidence": None}])


def test_student_can_leave_a_subject_but_not_remove_a_classmate(school):
    sid = school["subject_id"]; asha, bilal = (school["students"][n]["user"]["student_id"] for n in ("Asha", "Bilal"))
    with as_(school["students"]["Asha"]):
        enrollment_service.unenroll(bilal, sid)                                              # silently affects 0 rows (RLS)
        enrollment_service.unenroll(asha, sid)
    with as_(school["t1"]):
        assert [r["name"] for r in enrollment_service.subject_roster(sid)] == ["Bilal", "Chen"]


def test_roster_larger_than_postgrest_row_cap_is_fully_returned(school):
    cur, sid = school["cur"], school["subject_id"]
    cur.execute("insert into students(name) select 'S' || g from generate_series(1, 1200) g")
    cur.execute("insert into enrollments(student_id, subject_id) select student_id, %s from students where name like 'S%%'", (sid,))
    with as_(school["t1"]):
        assert len(enrollment_service.subject_roster(sid)) == 1203
