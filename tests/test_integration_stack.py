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


# ═════════ dashboards over real JWT / PostgREST / RLS ═════════
def _take(school, present_names):
    t1, sid = school["t1"], school["subject_id"]
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        s = session_service.get_or_start(t1["user"]["teacher_id"], sid, "FACE")
        _, records = att.build_attendance_rows(roster, {r["student_id"]: Detection(r["student_id"], "P") for r in roster if r["name"] in present_names})
        session_service.confirm(t1["user"]["teacher_id"], s["session_id"], records)


def test_dashboards_end_to_end_with_isolation(school):
    from src.services import dashboard_service as ds
    _take(school, {"Asha", "Bilal"}); _take(school, {"Asha"})
    tid, sid = school["t1"]["user"]["teacher_id"], school["subject_id"]
    with as_(school["t1"]):
        ov = ds.teacher_overview(tid)
        assert (ov.total_subjects, ov.total_students, ov.sessions_today) == (1, 3, 2)
        assert ov.average_attendance == 50.0                      # (2+1+0)/6
        risks = {r["name"]: r["risk"] for r in ov.at_risk}
        # Bilal 1/2 and Chen 0/2 are below 75%; Asha 2/2 is on target but cannot miss a class (2/3 < 75%) so she is only "watch"
        assert risks == {"Bilal": "HIGH", "Chen": "HIGH", "Asha": "MEDIUM"}
        d = ds.subject_detail(tid, sid)
        assert [s["name"] for s in d["students"]] == ["Asha", "Bilal", "Chen"] and len(d["trend"]) == 2
        subject_service.set_target(sid, 90)
        assert subject_service.list_teacher_subjects(tid)[0]["target_percent"] == 90.0
    with as_(school["t2"]):
        t2 = school["t2"]["user"]["teacher_id"]
        assert ds.teacher_overview(t2).total_subjects == 0
        with pytest.raises(NotFoundError):
            ds.subject_detail(t2, sid)
        with pytest.raises(AuthorizationError):
            subject_service.set_target(sid, 10)                       # not the owner
    asha = school["students"]["Asha"]["user"]["student_id"]
    with as_(school["students"]["Asha"]):
        so = ds.student_overview(asha)
        assert (so.attended, so.conducted, so.overall_percentage, so.streak) == (2, 2, 100.0, 2)
        assert so.subjects[0][1].target == 90.0
    with as_(school["students"]["Bilal"]):
        assert ds.student_overview(school["students"]["Bilal"]["user"]["student_id"]).overall_percentage == 50.0
    with as_(school["students"]["Dev"]):
        assert ds.student_overview(school["students"]["Dev"]["user"]["student_id"]).subjects == []
    with as_(school["admin"]):
        a = admin_service.overview()
        assert (a["teachers"], a["students"], a["subjects"], a["conducted"]) == (2, 4, 1, 6)
    with as_(school["t1"]):
        with pytest.raises(AuthorizationError):
            admin_service.overview()
    with as_(school["students"]["Asha"]):
        with pytest.raises(AuthorizationError):
            admin_service.overview()


# ═════════ face samples + model-aware recognition over real JWT / PostgREST / RLS ═════════
def test_face_samples_and_model_filtered_recognition_end_to_end(school):
    import numpy as np
    from PIL import Image
    from src.pipelines.face_engine import COSINE, DetectedFace, FaceRecognitionEngine
    from src.repositories import student_repository
    from src.services import recognition_service as rs

    sid = school["subject_id"]
    asha, bilal = school["students"]["Asha"], school["students"]["Bilal"]
    vec = np.random.default_rng(7).normal(size=512); vec /= np.linalg.norm(vec)

    class Onnxish(FaceRecognitionEngine):
        model_id, metric, default_threshold, default_margin = "onnx-test", COSINE, 0.4, 0.05
        def detect_and_embed(self, image):
            return [DetectedFace((165, 10, 300, 160), vec + np.random.default_rng(1).normal(scale=0.002, size=512))]

    eng = Onnxish()
    with as_(asha):                                               # Asha adds an onnx-model sample of herself
        sample = rs.prepare_face_sample(Image.fromarray(__import__("skimage.data").data.astronaut()), eng)
        student_repository.add_face_sample(sample.embedding, sample.model_id)
        assert student_repository.my_face_sample_counts() == {"dlib-resnet-128": 1, "onnx-test": 1}
        assert student_repository.get_face_gallery([asha["user"]["student_id"]]) == {}   # RLS: a student gets no templates, not even their own
    t1 = school["t1"]
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        assert set(student_repository.get_face_gallery([r["student_id"] for r in roster], "onnx-test")) == {asha["user"]["student_id"]}
        res = rs.analyze_photos([Image.fromarray(__import__("skimage.data").data.astronaut())], roster, eng)
        assert set(res.detections) == {asha["user"]["student_id"]} and res.detections[asha["user"]["student_id"]].confidence > 0.95
        # Bilal and Chen only have dlib templates, so under the onnx model they cannot be recognised - and the teacher is told
        chen = school["students"]["Chen"]["user"]["student_id"]
        assert set(res.students_without_templates) == {bilal["user"]["student_id"], chen}
        assert any("no face data" in n for n in res.notes())
    with as_(school["t2"]):                                                               # another teacher's roster sees nothing
        assert student_repository.get_face_gallery(None, "onnx-test") == {}


def test_fused_face_plus_voice_session_is_saved_with_source_and_confidence(school):
    from src.services import fusion_service
    from src.services.recognition_service import PhotoAnalysis, VoiceAnalysis
    t1, sid = school["t1"], school["subject_id"]
    ids = {n: school["students"][n]["user"]["student_id"] for n in ("Asha", "Bilal", "Chen")}
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        s = session_service.get_or_start(t1["user"]["teacher_id"], sid, "FACE_PLUS_VOICE")
        assert s["method"] == "FACE_PLUS_VOICE"
        face = PhotoAnalysis(detections={ids["Asha"]: Detection(ids["Asha"], "Photo 1", 0.9), ids["Bilal"]: Detection(ids["Bilal"], "Photo 1", 0.4)})
        voice = VoiceAnalysis(detections={ids["Asha"]: Detection(ids["Asha"], "Voice", 0.8), ids["Chen"]: Detection(ids["Chen"], "Voice", 0.9)})
        result = fusion_service.fuse(roster, face, voice)
        _, records = fusion_service.rows_and_records(roster, result)
        assert session_service.confirm(t1["user"]["teacher_id"], s["session_id"], records) == 3
    by_src = {r["student_id"]: r for r in records}
    assert by_src[ids["Asha"]]["source"] == "Face+Voice" and by_src[ids["Chen"]]["source"] == "Voice" and by_src[ids["Bilal"]]["source"] == "Face"
    cur = school["cur"]
    cur.execute("select s.name, r.status, r.source, r.confidence from attendance_records r join students s using(student_id) order by s.name")
    rows = {n: (st, src, c) for n, st, src, c in cur.fetchall()}
    assert rows["Asha"][:2] == ("PRESENT", "Face+Voice") and rows["Asha"][2] > 0.9
    assert rows["Chen"][:2] == ("PRESENT", "Voice") and rows["Bilal"][:2] == ("PRESENT", "Face")


# ═════════════════════════ Phase 9: analytics, forecasts, anomalies over RLS ═════════════════════════
def _session(school, present_names, stats=None):
    t1, sid = school["t1"], school["subject_id"]
    with as_(t1):
        roster = enrollment_service.subject_roster(sid)
        s = session_service.get_or_start(t1["user"]["teacher_id"], sid, "FACE")
        if stats:
            session_service.record_recognition_stats(t1["user"]["teacher_id"], s["session_id"], stats)
        _, records = att.build_attendance_rows(roster, {r["student_id"]: Detection(r["student_id"], "P", 0.9) for r in roster if r["name"] in present_names})
        session_service.confirm(t1["user"]["teacher_id"], s["session_id"], records)
        return s["session_id"]


def test_analytics_end_to_end_with_isolation(school):
    from src.services import analytics_service as an_s
    bad = {"faces": 10, "unknown": 5}
    for names in ({"Asha", "Bilal"}, {"Asha"}, {"Asha"}, {"Asha", "Chen"}, {"Asha"}, {"Asha"}):
        _session(school, names, bad)
    tid, sid = school["t1"]["user"]["teacher_id"], school["subject_id"]
    with as_(school["t1"]):
        ta = an_s.teacher_analytics(tid, sid, "week")
        assert ta.participation["sessions"] == 6 and ta.class_average == 44.4 and ta.highest["name"] == "Asha" and ta.highest["percentage"] == 100.0
        assert ta.lowest["percentage"] <= 20 and sum(b["count"] for b in ta.distribution) == 3
        assert len(ta.heatmap) == 3 * 6 and ta.totals["present"] == 8
        by = {f["name"]: f["forecast"] for f in ta.forecasts}
        assert by["Asha"].risk == "LOW" and by["Chen"].risk == "HIGH" and ta.forecasts[0]["forecast"].risk == "HIGH"
        flags = an_s.teacher_anomalies(tid)
        assert any(a.code == "RECOGNITION_FAILURES" and a.evidence.get("repeated") for a in flags)          # 6 sessions with 50% unknown faces
        assert an_s.subject_comparison(tid)[0]["percentage"] == 44.4
    with as_(school["t2"]):
        t2 = school["t2"]["user"]["teacher_id"]
        with pytest.raises(NotFoundError):
            an_s.teacher_analytics(t2, sid)
        assert an_s.teacher_anomalies(t2) == []
    asha = school["students"]["Asha"]["user"]["student_id"]
    with as_(school["students"]["Asha"]):
        sa = an_s.student_analytics(asha)
        sub, f = sa.forecasts[0]
        assert f.conducted == 6 and f.current_pct == 100.0 and f.risk == "LOW" and sa.weekly and sa.subject_comparison[0]["percentage"] == 100.0
    with as_(school["students"]["Chen"]):
        _, f = an_s.student_analytics(school["students"]["Chen"]["user"]["student_id"]).forecasts[0]
        assert f.conducted == 6 and f.risk == "HIGH" and f.consecutive_absences == 2 and any("below" in r for r in f.reasons)
    with as_(school["students"]["Dev"]):
        assert an_s.student_analytics(school["students"]["Dev"]["user"]["student_id"]).forecasts == []
    with as_(school["admin"]):
        assert any(a.code == "RECOGNITION_FAILURES" for a in an_s.admin_anomalies())
    from src.repositories import analytics_repository as ar
    with as_(school["students"]["Dev"]):                                    # not enrolled anywhere: sees no sessions, no records
        assert ar.sessions_detail([sid]) == [] and ar.records_for_sessions([1, 2, 3]) == []
    with as_(school["students"]["Bilal"]):                                  # sees sessions he has a record in, but only his own records
        assert {r["student_id"] for r in ar.records_for_sessions([1, 2, 3, 4, 5, 6])} == {school["students"]["Bilal"]["user"]["student_id"]}


# ═════════════════════════ Phase 10: assistant over real JWT / RLS ═════════════════════════
def test_assistant_answers_are_scoped_by_the_database(school):
    from src.services import assistant_service as asst
    for names in ({"Asha", "Bilal"}, {"Asha"}, {"Asha", "Chen"}, {"Asha"}):
        _session(school, names)
    S = school["students"]
    with as_(S["Asha"]):
        a = asst.ask("What is my attendance?")
        assert "Overall you have attended 4 of 4 classes (100%)" in a.text and "DSA" in a.text
        assert "can miss up to" in asst.ask("Can I miss 1 more DSA class?").text
    with as_(S["Bilal"]):
        b = asst.ask("What is my attendance?")
        assert "1 of 4 classes (25%)" in b.text and "100%" not in b.text                  # his own numbers, never Asha's
        assert asst.ask("Can I miss 1 more DSA class?").text.startswith("No")
        assert "Which students" not in asst.ask("Which students are below 75%?").text      # no teacher tool for a student
    with as_(S["Dev"]):                                                                    # not enrolled anywhere
        assert "No classes have been recorded" in asst.ask("What is my attendance?").text
        assert "Which subject" in asst.ask("Can I miss 2 DSA classes?").text
    with as_(school["t1"]):
        t = asst.ask("Which students are below 75%?")
        assert "Bilal" in t.text and "Chen" in t.text and "Asha" not in t.text and "Dev" not in t.text
        m = asst.ask("Which students missed the last 1 classes in DSA1?").text
        assert "Bilal" in m and "Chen" in m and "Asha" not in m                            # only Asha was present in the last class
        assert "4 sessions" in asst.ask("Show attendance for DSA1").text
    with as_(school["t2"]):                                                                # another teacher: sees none of T1's data
        assert "Which subject" in asst.ask("Show attendance for DSA1").text                # T2 owns no subject called DSA1
        assert "No student is below" in asst.ask("Which students are below 75%?").text
    with as_(school["admin"]):
        with pytest.raises(AuthorizationError):
            asst.ask("anything")
