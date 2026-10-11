"""Enrolment invites end to end (real PostgreSQL + PostgREST + JWT + RLS)."""
import pytest

from tests.test_integration_stack import URL, DSN, SECRET, as_, pg, school, PW  # noqa: F401  (fixtures)
from src.services import invite_service as inv, enrollment_service
from src.utils.errors import AuthorizationError, NotFoundError, ValidationError

pytestmark = pytest.mark.skipif(not (URL and DSN and SECRET), reason="integration env vars not set")


def _make(school, **kw):
    with as_(school["t1"]):
        return inv.create(school["subject_id"], **{"ttl_minutes": 60, "max_uses": 1, **kw})


def _redeem(school, who, token):
    with as_(school["students"][who]):
        return inv.redeem(token)


def test_token_is_never_stored_and_link_contains_it(school):
    made = _make(school)
    school["cur"].execute("select token_hash from subject_invites")
    (stored,) = school["cur"].fetchone()
    assert made["token"] not in stored and stored == inv.hash_token(made["token"]) and made["token"] in made["url"]
    with as_(school["t1"]):                                                          # the clients cannot even read the hash column
        assert all("token_hash" not in i for i in inv.list_invites(school["subject_id"]))


def test_single_use_invite_enrols_once_and_then_is_used_up(school):
    made = _make(school)
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.ENROLLED
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.ALREADY_ENROLLED     # does not consume a use
    school_students = school["students"]
    # a second student cannot use a spent single-use invite (Dev enrolled; Asha etc. are already enrolled, so register another)
    from src.services import auth_service
    from tests.test_integration_stack import emb
    auth_service.register_student("eve@x.co", "Eve", PW["password"], PW["confirm"], "R9", emb(9), None, True)
    school_students["Eve"] = auth_service.login("eve@x.co", PW["password"], "STUDENT")
    assert _redeem(school, "Eve", made["token"])[0] is inv.Redeem.USED_UP


def test_expired_revoked_unopened_and_unknown_tokens_are_rejected(school):
    made = _make(school, max_uses=5)
    school["cur"].execute("update subject_invites set expires_at = now() - interval '1 minute', opens_at = now() - interval '2 minutes'")
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.EXPIRED
    school["cur"].execute("update subject_invites set expires_at = now() + interval '1 hour', opens_at = now() + interval '30 minutes'")
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.NOT_OPEN
    school["cur"].execute("update subject_invites set opens_at = now() - interval '1 minute'")
    with as_(school["t1"]):
        (invite,) = inv.list_invites(school["subject_id"])
        inv.revoke(invite["invite_id"])
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.REVOKED
    assert _redeem(school, "Dev", inv.new_token())[0] is inv.Redeem.NOT_FOUND
    with pytest.raises(ValidationError):
        _redeem(school, "Dev", "short")
    school["cur"].execute("select count(*) from enrollments where student_id = (select student_id from students where name = 'Dev')")
    assert school["cur"].fetchone()[0] == 0


def test_approval_flow_request_then_teacher_decides(school):
    made = _make(school, max_uses=5, require_approval=True)
    outcome, info = _redeem(school, "Dev", made["token"])
    assert outcome is inv.Redeem.PENDING_APPROVAL and info["name"] == "DSA"
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.PENDING_APPROVAL      # idempotent: still one request, one use
    school["cur"].execute("select count(*) from enrollment_requests"); assert school["cur"].fetchone()[0] == 1
    school["cur"].execute("select uses from subject_invites"); assert school["cur"].fetchone()[0] == 1
    with as_(school["students"]["Dev"]):
        assert enrollment_service.student_subjects(0) is not None and not [s for s in enrollment_service.student_subjects(4) if s["name"] == "DSA"]
    with as_(school["t2"]):                                                              # another teacher sees nothing and cannot decide
        assert inv.pending_requests() == []
    with as_(school["t1"]):
        (req,) = inv.pending_requests()
        assert req["student"] == "Dev" and "email" not in req
        with as_(school["t2"]):
            with pytest.raises(NotFoundError):
                inv.decide(req["request_id"], True)
        assert inv.decide(req["request_id"], True) == "APPROVED"
        with pytest.raises(Exception):
            inv.decide(req["request_id"], False)                                         # already decided
    assert _redeem(school, "Dev", made["token"])[0] is inv.Redeem.ALREADY_ENROLLED
    with as_(school["admin"]):
        from src.services import admin_service
        actions = [a["action"] for a in admin_service.audit_log()]
    assert {"invite.created", "enrollment.requested", "enrollment.approved"} <= set(actions)


def test_rejected_request_does_not_enrol(school):
    made = _make(school, require_approval=True)
    _redeem(school, "Dev", made["token"])
    with as_(school["t1"]):
        (req,) = inv.pending_requests()
        assert inv.decide(req["request_id"], False) == "REJECTED"
    school["cur"].execute("select count(*) from enrollments e join students s using (student_id) where s.name = 'Dev'")
    assert school["cur"].fetchone()[0] == 0


def test_only_the_owner_can_create_revoke_or_list(school):
    made = _make(school)
    with as_(school["t2"]):
        with pytest.raises((NotFoundError, AuthorizationError)):
            inv.create(school["subject_id"], 60, 1)
        assert inv.list_invites(school["subject_id"]) == []                              # RLS hides another teacher's invites
        with pytest.raises((NotFoundError, AuthorizationError)):
            inv.revoke(1)
    with as_(school["students"]["Asha"]):
        with pytest.raises((NotFoundError, AuthorizationError)):
            inv.create(school["subject_id"], 60, 1)
        assert inv.list_invites(school["subject_id"]) == []
    with as_(school["t1"]):
        assert len(inv.list_invites(school["subject_id"])) == 1


def test_parameter_limits_are_enforced_by_the_database(school):
    with as_(school["t1"]):
        for kw in ({"ttl_minutes": 1}, {"ttl_minutes": 99999}, {"max_uses": 0}, {"max_uses": 5000}, {"opens_in_minutes": 61}):
            with pytest.raises(ValidationError):
                inv.create(school["subject_id"], **{"ttl_minutes": 60, "max_uses": 1, **kw})


def test_concurrent_style_overuse_cannot_exceed_max_uses(school):
    made = _make(school, max_uses=1)
    from src.services import auth_service
    from tests.test_integration_stack import emb
    for i, n in enumerate(("Fay", "Gus"), 20):
        auth_service.register_student(f"{n.lower()}@x.co", n, PW["password"], PW["confirm"], f"R{i}", emb(i), None, True)
        school["students"][n] = auth_service.login(f"{n.lower()}@x.co", PW["password"], "STUDENT")
    results = [_redeem(school, n, made["token"])[0] for n in ("Fay", "Gus")]
    assert results == [inv.Redeem.ENROLLED, inv.Redeem.USED_UP]
    school["cur"].execute("select uses, max_uses from subject_invites"); assert school["cur"].fetchone() == (1, 1)


def test_state_of_pure_logic():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = {"revoked_at": None, "expires_at": (now + timedelta(hours=1)).isoformat(), "opens_at": (now - timedelta(hours=1)).isoformat(), "uses": 0, "max_uses": 2}
    assert inv.state_of(base, now) == "VALID" and inv.state_of({**base, "uses": 2}, now) == "USED_UP"
    assert inv.state_of({**base, "revoked_at": "x"}, now) == "REVOKED" and inv.state_of({**base, "expires_at": (now - timedelta(seconds=1)).isoformat()}, now) == "EXPIRED"
    assert inv.state_of({**base, "opens_at": (now + timedelta(minutes=1)).isoformat()}, now) == "NOT_OPEN"


# ───── reports against the real database ─────
def test_subject_report_matches_the_database_and_is_isolated(school):
    from tests.test_integration_stack import _take
    from src.services import report_service as rs
    from src.utils.errors import NotFoundError
    _take(school, ["Asha", "Bilal"])
    _take(school, ["Asha"])
    with as_(school["t1"]):
        report = rs.subject_report(school["t1"]["user"]["teacher_id"], school["subject_id"])
        by_name = {r["Student"]: r for r in report["students"]}
        assert by_name["Asha"]["Attended"] == 2 and by_name["Asha"]["Classes"] == 2 and by_name["Asha"]["Attendance %"] == 100
        assert by_name["Bilal"]["Attended"] == 1 and by_name["Chen"]["Attended"] == 0 and by_name["Chen"]["Classes"] == 2
        assert len(report["sessions"]) == 2 and report["matrix"] and rs.to_csv(report["students"]).count(b"\n") == 4
        assert rs.subject_workbook(report)[:2] == b"PK"
    with as_(school["t2"]):
        with pytest.raises(NotFoundError):
            rs.subject_report(school["t2"]["user"]["teacher_id"], school["subject_id"])
    with as_(school["students"]["Asha"]):
        rows = rs.student_history_rows(school["students"]["Asha"]["user"]["student_id"])
        assert len(rows) == 2 and {r["Status"] for r in rows} == {"Present"}
        assert rs.student_history_rows(school["students"]["Bilal"]["user"]["student_id"]) == []        # RLS: another student's records are invisible
