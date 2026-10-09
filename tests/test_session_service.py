"""Session workflow rules with a fake repository (DB semantics are covered by test_db_schema / integration)."""
import pytest

from src.repositories import session_repository as repo
from src.services import session_service as svc
from src.utils.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError


class Fake:
    def __init__(self):
        self.sessions, self.next = {}, 1
        self.calls = []
        self.actor = 1

    def create(self, subject_id, method, location=None):
        if any(s["subject_id"] == subject_id and s["status"] == "OPEN" for s in self.sessions.values()):
            raise ConflictError("open exists")
        sid, self.next = self.next, self.next + 1
        self.sessions[sid] = {"session_id": sid, "subject_id": subject_id, "teacher_id": self.actor, "method": method, "status": "OPEN"}
        return sid

    def get(self, sid): return self.sessions.get(sid)
    def find_open(self, subject_id): return next((s for s in self.sessions.values() if s["subject_id"] == subject_id and s["status"] == "OPEN"), None)

    def complete(self, sid, records):
        if self.sessions[sid]["status"] != "OPEN":
            raise ConflictError("not open")
        self.sessions[sid]["status"] = "COMPLETED"; return len(records)

    def cancel(self, sid):
        if self.sessions[sid]["status"] != "OPEN":
            raise ConflictError("not open")
        self.sessions[sid]["status"] = "CANCELLED"


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    for name in ("create", "get", "find_open", "complete", "cancel"):
        monkeypatch.setattr(repo, name, getattr(f, name))
    return f


def test_get_or_start_reuses_open_session_instead_of_duplicating(fake):
    a = svc.get_or_start(1, 10, "FACE")
    b = svc.get_or_start(1, 10, "FACE")
    assert a["session_id"] == b["session_id"] and len(fake.sessions) == 1


def test_open_session_with_other_method_must_be_finished_first(fake):
    svc.get_or_start(1, 10, "FACE")
    with pytest.raises(ConflictError) as ei:
        svc.get_or_start(1, 10, "VOICE")
    assert "FACE" in ei.value.user_message


def test_other_teacher_cannot_join_or_read_a_session(fake):
    s = svc.get_or_start(1, 10, "FACE")
    with pytest.raises(AuthorizationError):
        svc.get_or_start(2, 10, "FACE")
    with pytest.raises(AuthorizationError):
        svc.get_owned_session(2, s["session_id"])
    with pytest.raises(NotFoundError):
        svc.get_owned_session(1, 999)


def test_invalid_method_rejected(fake):
    with pytest.raises(ValidationError):
        svc.get_or_start(1, 10, "TELEPATHY")


def test_confirm_is_idempotent_after_completion_but_not_after_cancel(fake):
    s = svc.get_or_start(1, 10, "FACE")
    assert svc.confirm(1, s["session_id"], [{"student_id": 1}]) == 1
    assert svc.confirm(1, s["session_id"], [{"student_id": 1}]) == 0          # double click
    t = svc.get_or_start(1, 10, "FACE")
    svc.discard(1, t["session_id"])
    with pytest.raises(ConflictError):
        svc.confirm(1, t["session_id"], [])


def test_discard_is_idempotent_but_cannot_cancel_completed(fake):
    s = svc.get_or_start(1, 10, "FACE")
    svc.discard(1, s["session_id"]); svc.discard(1, s["session_id"])
    done = svc.get_or_start(1, 10, "FACE"); svc.confirm(1, done["session_id"], [])
    with pytest.raises(ConflictError):
        svc.discard(1, done["session_id"])


def test_correction_requires_a_reason_before_hitting_the_db(fake, monkeypatch):
    monkeypatch.setattr(repo, "correct", lambda *a: pytest.fail("must not be called"))
    with pytest.raises(ValidationError):
        svc.correct_record(1, 1, 1, "LATE", "   ")


def test_undoable_corrections_are_the_latest_active_per_record():
    cs = [
        {"correction_id": 5, "record_id": 1, "reverted_at": None},
        {"correction_id": 4, "record_id": 1, "reverted_at": None},
        {"correction_id": 3, "record_id": 1, "reverted_at": "t"},
        {"correction_id": 6, "record_id": 2, "reverted_at": None},
        {"correction_id": 7, "record_id": 3, "reverted_at": "t"},
    ]
    assert [c["correction_id"] for c in svc.undoable_corrections(cs)] == [6, 5]


def test_list_sessions_tallies_and_formats(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    sub = {"name": "DSA", "subject_code": "D1"}
    monkeypatch.setattr(repo, "list_for_teacher", lambda t: [
        {"session_id": 2, "subjects": sub, "method": "FACE", "status": "OPEN", "started_at": "2026-01-02T04:30:00+00:00"},
        {"session_id": 1, "subjects": sub, "method": "VOICE", "status": "COMPLETED", "started_at": "2026-01-01T10:00:00+00:00"},
    ])
    monkeypatch.setattr(repo, "records_for_sessions", lambda ids: [
        {"session_id": 1, "status": "PRESENT"}, {"session_id": 1, "status": "LATE"}, {"session_id": 1, "status": "ABSENT"},
        {"session_id": 1, "status": "EXCUSED"},
    ])
    df = svc.list_sessions(1)
    assert list(df["Attendance"]) == ["in progress", "✅ 2 / 3"]                # excused not counted
    assert df.iloc[0]["Time"] == "2026-01-02 10:00 AM"                         # UTC → IST
    assert svc.list_sessions.__name__ and list(df["ID"]) == [2, 1]


def test_list_sessions_empty(monkeypatch):
    monkeypatch.setattr(repo, "list_for_teacher", lambda t: [])
    assert svc.list_sessions(1).empty
