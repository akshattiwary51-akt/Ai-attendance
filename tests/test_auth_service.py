import pytest

from src.repositories import account_repository, profile_repository
from src.security.auth_provider import set_auth_provider
from src.security.principal import current_principal
from src.services import auth_service
from src.utils.errors import AuthenticationError, DatabaseError, DuplicateError, ValidationError
from tests.fakes import FakeAuthProvider

GOOD = dict(password="correct-horse", confirm="correct-horse")


@pytest.fixture
def env(monkeypatch):
    provider = FakeAuthProvider()
    set_auth_provider(provider)
    provisioned, profiles = [], {}
    def provision(user_id, role, name, email, **kw):
        provisioned.append((user_id, role, name, email, kw)); return len(provisioned)
    monkeypatch.setattr(account_repository, "provision", provision)

    seen_principals = []
    def get_profile(uid):
        seen_principals.append(current_principal())
        return profiles.get(uid)
    monkeypatch.setattr(profile_repository, "get_own_profile", get_profile)
    yield provider, provisioned, profiles, seen_principals
    set_auth_provider(None)


def profile(role="TEACHER", active=True, **extra):
    base = {"role": role, "is_active": active, "teacher_id": 1 if role == "TEACHER" else None,
            "student_id": 2 if role == "STUDENT" else None, "teachers": {"name": "Ananya"} if role == "TEACHER" else None,
            "students": {"name": "Hamza"} if role == "STUDENT" else None}
    return {**base, **extra}


# ── registration ──
def test_teacher_registration_requires_approval_by_default(env):
    provider, provisioned, *_ = env
    result = auth_service.register_teacher(" Ananya@College.EDU ", "Ananya", **GOOD)
    assert result.pending_approval is True
    assert provisioned[0][1:4] == ("TEACHER", "Ananya", "ananya@college.edu") and provisioned[0][4]["active"] is False
    assert "ananya@college.edu" in provider.users                                    # email normalised


def test_teacher_registration_can_skip_approval(env, monkeypatch):
    monkeypatch.setenv("REQUIRE_TEACHER_APPROVAL", "false")
    from src.config import settings; settings.get_settings.cache_clear()
    assert auth_service.register_teacher("a@b.co", "A", **GOOD).pending_approval is False
    assert env[1][0][4]["active"] is True


@pytest.mark.parametrize("email,name,pw,confirm", [
    ("not-an-email", "N", "password1", "password1"), ("a@b.co", "  ", "password1", "password1"),
    ("a@b.co", "N", "short", "short"), ("a@b.co", "N", "password1", "different1"), ("a@b.co", "N", "x" * 73, "x" * 73),
    ("", "N", "password1", "password1"),
])
def test_registration_validation_creates_nothing(env, email, name, pw, confirm):
    with pytest.raises(ValidationError):
        auth_service.register_teacher(email, name, pw, confirm)
    assert not env[0].users and not env[1]


def test_provisioning_failure_removes_the_auth_user(env, monkeypatch):
    provider, *_ = env
    monkeypatch.setattr(account_repository, "provision", lambda *a, **k: (_ for _ in ()).throw(DatabaseError("boom")))
    with pytest.raises(DatabaseError):
        auth_service.register_teacher("a@b.co", "A", **GOOD)
    assert provider.deleted == ["user-1"]                                            # no orphan login without a profile


def test_duplicate_email_is_a_friendly_validation_error_and_cleans_up(env, monkeypatch):
    provider, *_ = env
    monkeypatch.setattr(account_repository, "provision", lambda *a, **k: (_ for _ in ()).throw(DuplicateError("dup")))
    with pytest.raises(ValidationError) as ei:
        auth_service.register_teacher("a@b.co", "A", **GOOD)
    assert "already exists" in ei.value.user_message and provider.deleted == ["user-1"]


def test_cleanup_failure_does_not_mask_the_original_error(env, monkeypatch):
    provider, *_ = env
    provider.fail_delete = True
    monkeypatch.setattr(account_repository, "provision", lambda *a, **k: (_ for _ in ()).throw(DatabaseError("boom")))
    with pytest.raises(DatabaseError):
        auth_service.register_teacher("a@b.co", "A", **GOOD)


def test_student_registration_needs_consent_and_a_face(env):
    kw = dict(email="s@x.co", name="S", roll_number="R1", voice_embedding=None, **GOOD)
    with pytest.raises(ValidationError, match="consent|biometric") as e1:
        auth_service.register_student(face_embedding=[0.1] * 128, consent=False, **kw)
    assert "biometric" in e1.value.user_message
    with pytest.raises(ValidationError) as e2:
        auth_service.register_student(face_embedding=None, consent=True, **kw)
    assert "face photo" in e2.value.user_message
    assert not env[1]
    auth_service.register_student(face_embedding=[0.1] * 128, consent=True, **kw)
    _, role, _, _, extra = env[1][0]
    assert role == "STUDENT" and extra["roll_number"] == "R1" and extra["face"] == [0.1] * 128 and "active" not in extra


# ── login ──
def test_login_success_returns_tokens_role_and_name(env):
    provider, _, profiles, seen = env
    uid = provider.sign_up("t@x.co", "pw-12345"); profiles[uid] = profile("TEACHER")
    out = auth_service.login(" T@X.co ", "pw-12345", "TEACHER")
    assert out["user"] == {"teacher_id": 1, "student_id": None, "name": "Ananya", "email": "t@x.co"}
    assert out["auth"]["role"] == "TEACHER" and out["auth"]["access_token"] == f"access-{uid}"
    assert seen[0].access_token == f"access-{uid}" and current_principal() is None      # principal only used during the lookup


def test_login_wrong_password_unknown_user_and_blank(env):
    provider, _, profiles, _ = env
    provider.sign_up("t@x.co", "pw-12345")
    for e, p in [("t@x.co", "nope"), ("ghost@x.co", "pw-12345"), ("", ""), ("t@x.co", "")]:
        with pytest.raises(AuthenticationError):
            auth_service.login(e, p, "TEACHER")


@pytest.mark.parametrize("prof,expected,fragment", [
    (profile("TEACHER", active=False), "TEACHER", "pending approval"),
    (None, "TEACHER", "isn't set up"),
    (profile("STUDENT"), "TEACHER", "student account"),
    (profile("TEACHER"), "ADMIN", "teacher account"),
])
def test_login_rejects_inactive_missing_or_wrong_role_and_signs_out(env, prof, expected, fragment):
    provider, _, profiles, _ = env
    uid = provider.sign_up("t@x.co", "pw-12345")
    if prof: profiles[uid] = prof
    with pytest.raises(AuthenticationError) as ei:
        auth_service.login("t@x.co", "pw-12345", expected)
    assert fragment in ei.value.user_message
    assert provider.signed_out == [f"access-{uid}"]                                 # the just-issued session is revoked


def test_admin_login_uses_fallback_name(env):
    provider, _, profiles, _ = env
    uid = provider.sign_up("root@x.co", "pw-12345")
    profiles[uid] = {"role": "ADMIN", "is_active": True, "teacher_id": None, "student_id": None, "teachers": None, "students": None}
    assert auth_service.login("root@x.co", "pw-12345", "ADMIN")["user"]["name"] == "Admin"


# ── token refresh ──
def test_needs_refresh_margin():
    assert auth_service.needs_refresh(1000, now=941) is True and auth_service.needs_refresh(1000, now=900) is False


def test_refresh_merges_new_tokens_and_failure_raises(env):
    out = auth_service.refresh({"user_id": "u9", "refresh_token": "refresh-u9", "access_token": "old", "expires_at": 1, "role": "TEACHER"})
    assert out["access_token"] == "access2-u9" and out["role"] == "TEACHER"
    with pytest.raises(AuthenticationError):
        auth_service.refresh({"refresh_token": "bad-token"})


def test_logout_revokes_server_session(env):
    auth_service.logout("tok"); auth_service.logout(None)
    assert env[0].signed_out == ["tok"]


def test_create_admin_provisions_an_admin_profile(env):
    provider, provisioned, *_ = env
    auth_service.create_admin("Root@College.edu", "long-password")
    assert provisioned[0][1:4] == ("ADMIN", "Administrator", "root@college.edu") and "root@college.edu" in provider.users
    with pytest.raises(ValidationError):
        auth_service.create_admin("bad", "long-password")


def test_create_admin_cleans_up_when_provisioning_fails(env, monkeypatch):
    monkeypatch.setattr(account_repository, "provision", lambda *a, **k: (_ for _ in ()).throw(DatabaseError("boom")))
    with pytest.raises(DatabaseError):
        auth_service.create_admin("root@college.edu", "long-password")
    assert env[0].deleted == ["user-1"]
