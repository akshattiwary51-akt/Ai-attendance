"""Migration 0005: multi-sample voice templates (real PostgreSQL)."""
import pytest

psycopg2 = pytest.importorskip("psycopg2")
from tests.db_support import code, db, dsn, emb, one, requires_db, run, world  # noqa: E402,F401

pytestmark = requires_db
ADD = "select add_voice_sample(%s::jsonb, %s, %s)"


def test_up_to_five_samples_per_model_with_quality_and_audit(world):
    start = one(world, "super", "select count(*) from voice_profiles where student_id=1 and is_active")     # fixture gives s1 one sample
    for _ in range(5 - start):
        assert one(world, "s1", ADD, emb(256, 0.2), "resemblyzer", 88)
    assert code(world, "s1", ADD, emb(256, 0.2), "resemblyzer", None) == "PT409"
    assert one(world, "s1", ADD, emb(256, 0.2), "other-model", None)                       # own quota per model
    assert run(world, "s1", "select * from my_voice_sample_counts()") == [("other-model", 1), ("resemblyzer", 5)]
    assert one(world, "super", "select count(*) from voice_profiles where quality_score=88") == 5 - start
    assert one(world, "super", "select count(*) from audit_logs where action='voice.sample_added'") == 5 - start + 1


def test_only_students_and_valid_inputs(world):
    assert code(world, "t1", ADD, emb(256), "m", None) == "PT403"
    assert code(world, "admin", ADD, emb(256), "m", None) == "PT403"
    assert code(world, None, ADD, emb(256), "m", None) == "42501"
    assert code(world, "s1", ADD, emb(10), "m", None) == "PT422"
    assert code(world, "s1", ADD, emb(256), " ", None) == "PT422"
    assert code(world, "s1", ADD, emb(256), "m", 120) == "23514"                           # quality is 0..100


def test_remove_samples_is_scoped_to_the_caller_and_model(world):
    one(world, "s1", ADD, emb(256, 0.2), "other-model", None)
    assert one(world, "s1", "select remove_voice_samples('other-model')") == 1
    assert run(world, "s1", "select * from my_voice_sample_counts()") == [("resemblyzer", 1)]
    s2_before = one(world, "super", "select count(*) from voice_profiles where student_id=2 and is_active")
    assert one(world, "s2", "select remove_voice_samples('resemblyzer')") == s2_before         # only their own rows
    assert one(world, "super", "select count(*) from voice_profiles where student_id=1 and is_active") == 1   # s1 untouched
    assert code(world, "t1", "select remove_voice_samples('resemblyzer')") == "PT403"


def test_teachers_see_templates_only_of_their_students_and_students_none(world):
    assert run(world, "s1", "select * from voice_profiles") == []
    assert run(world, "s2", "select * from voice_profiles") == []
