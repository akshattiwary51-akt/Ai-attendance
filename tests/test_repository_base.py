import pytest

from src.repositories import _base
from src.utils.errors import ConfigurationError, DatabaseError, DuplicateError
from tests.conftest import FakeQuery


def test_fetch_all_pages_past_the_1000_row_limit():
    rows = [{"i": i} for i in range(2500)]
    queries = []

    def make():
        q = FakeQuery(rows); queries.append(q); return q

    assert len(_base.fetch_all(make, "t")) == 2500   # previously silently truncated at 1000
    assert len(queries) == 3


def test_fetch_all_exact_page_boundary_terminates():
    rows = [{"i": i} for i in range(2000)]
    assert len(_base.fetch_all(lambda: FakeQuery(rows), "t")) == 2000


class Boom:
    def __init__(self, code=None): self.code = code
    def execute(self):
        e = RuntimeError("boom"); e.code = self.code; raise e


def test_execute_translates_unique_violation():
    with pytest.raises(DuplicateError):
        _base.execute(Boom("23505"), "x")


def test_execute_translates_other_errors_without_leaking_details():
    with pytest.raises(DatabaseError) as ei:
        _base.execute(Boom("XX000"), "x")
    assert "boom" not in ei.value.user_message


def test_provision_unauthorized_reports_service_credential_configuration():
    error = _base.translate(Boom(401), "rpc.provision_account")
    assert isinstance(error, ConfigurationError)
    assert "SUPABASE_SERVICE_ROLE_KEY" in error.user_message


def test_chunked():
    assert list(_base.chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]


def test_internal_messages_never_become_user_messages():
    from src.utils.errors import AppError
    assert AppError("teacher.create failed").user_message == AppError.default_user_message
