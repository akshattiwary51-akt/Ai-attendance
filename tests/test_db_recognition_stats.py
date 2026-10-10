"""Migration 0006: session recognition stats (real PostgreSQL)."""
import json

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from tests.db_support import code, db, dsn, new_session, one, requires_db, run, world  # noqa: E402,F401

pytestmark = requires_db
SET = "select set_session_recognition_stats(%s, %s::jsonb)"


def test_owner_can_set_numeric_counters_on_an_open_session(world):
    sid = new_session(world)
    run(world, "t1", SET, sid, json.dumps({"faces": 10, "unknown": 2, "ambiguous": 1}))
    assert one(world, "super", "select recognition_stats->>'unknown' from attendance_sessions where session_id=%s", sid) == "2"


@pytest.mark.parametrize("payload", ['{"evil": 1}', '{"faces": "ten"}', '{"faces": -1}', '[1,2]', '"x"', 'null'])
def test_only_whitelisted_non_negative_numbers_are_accepted(world, payload):
    sid = new_session(world)
    assert code(world, "t1", SET, sid, payload) == "PT422"


def test_only_the_owner_on_an_open_session(world):
    sid = new_session(world)
    assert code(world, "t2", SET, sid, '{"faces": 1}') == "PT403"
    assert code(world, "s1", SET, sid, '{"faces": 1}') == "PT403"
    assert code(world, None, SET, sid, '{"faces": 1}') == "42501"
    assert code(world, "t1", SET, 9999, '{"faces": 1}') == "PT404"
    run(world, "t1", "select cancel_attendance_session(%s)", sid)
    assert code(world, "t1", SET, sid, '{"faces": 1}') == "PT409"
