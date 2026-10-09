"""In-memory stand-ins used by service/UI tests."""
from __future__ import annotations

from src.security.auth_provider import AuthSession
from src.utils.errors import AuthenticationError, ValidationError


class FakeAuthProvider:
    """Mimics Supabase Auth: users keyed by email, sessions with expiry, call log for assertions."""

    def __init__(self):
        self.users: dict[str, dict] = {}      # email -> {id, password}
        self.deleted: list[str] = []
        self.signed_out: list[str] = []
        self.refreshed: list[str] = []
        self.fail_delete = False
        self.now_expiry = 9_999_999_999
        self.counter = 0

    def sign_up(self, email, password):
        if email in self.users:
            raise ValidationError("exists", user_message="An account with this email already exists.")
        self.counter += 1
        self.users[email] = {"id": f"user-{self.counter}", "password": password}
        return self.users[email]["id"]

    def sign_in(self, email, password):
        u = self.users.get(email)
        if not u or u["password"] != password:
            raise AuthenticationError("bad credentials")
        return AuthSession(u["id"], f"access-{u['id']}", f"refresh-{u['id']}", self.now_expiry)

    def refresh(self, refresh_token):
        if refresh_token.startswith("bad"):
            raise AuthenticationError("expired")
        self.refreshed.append(refresh_token)
        uid = refresh_token.removeprefix("refresh-")
        return AuthSession(uid, f"access2-{uid}", f"refresh-{uid}", self.now_expiry)

    def sign_out(self, access_token):
        self.signed_out.append(access_token)

    def delete_user(self, user_id):
        if self.fail_delete:
            raise AuthenticationError("cannot delete")
        self.deleted.append(user_id)

    def create_confirmed_user(self, email, password):
        return self.sign_up(email, password)
