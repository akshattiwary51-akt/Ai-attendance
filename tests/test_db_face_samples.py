"""Migration 0004: model-aware, multi-sample face templates (real PostgreSQL)."""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from tests.db_support import code, count, db, dsn, emb, one, requires_db, run, world  # noqa: E402,F401

pytestmark = requires_db
ADD = "select add_face_sample(%s::jsonb, %s, %s)"


def test_provision_stores_the_face_model(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u)
    sid = one(world, "service", "select provision_account(%s,'STUDENT','Mo','mo@x.com',true,null,%s::jsonb,null,null,'onnx-w600k_mbf')", u, emb(128))
    assert one(world, "super", "select model from face_profiles where student_id=%s", sid) == "onnx-w600k_mbf"
    sid2 = one(world, "service", "select provision_account(%s,'STUDENT','Mo2','mo2@x.com',true,null,%s::jsonb)", _new_user(world), emb(128))
    assert one(world, "super", "select model from face_profiles where student_id=%s", sid2) == "dlib-resnet-128"      # default preserved


def _new_user(world):
    u = str(uuid.uuid4()); run(world, "super", "insert into auth.users(id) values (%s)", u); return u


def test_student_adds_samples_up_to_five_per_model(world):
    for _ in range(4):                                   # s1 already has one dlib sample from the fixture
        assert one(world, "s1", ADD, emb(128, 0.2), "dlib-resnet-128", 80)
    assert code(world, "s1", ADD, emb(128, 0.2), "dlib-resnet-128", None) == "PT409"
    assert one(world, "s1", ADD, emb(512, 0.2), "onnx-w600k_mbf", None)                 # a different model has its own quota
    assert run(world, "s1", "select * from my_face_sample_counts()") == [("dlib-resnet-128", 5), ("onnx-w600k_mbf", 1)]
    assert one(world, "super", "select count(*) from audit_logs where action='face.sample_added'") == 5


def test_only_students_may_add_and_inputs_are_validated(world):
    assert code(world, "t1", ADD, emb(128), "m", None) == "PT403"
    assert code(world, "admin", ADD, emb(128), "m", None) == "PT403"
    assert code(world, None, ADD, emb(128), "m", None) in ("42501",)                     # anon has no execute
    assert code(world, "s1", ADD, emb(10), "m", None) == "PT422"                         # wrong dimension
    assert code(world, "s1", ADD, '{"a":1}', "m", None) == "PT422"
    assert code(world, "s1", ADD, emb(128), "  ", None) == "PT422"
    assert code(world, "s1", ADD, emb(128), "x" * 65, None) == "PT422"
    assert code(world, "s1", ADD, emb(128), "m", 150) == "23514"                         # quality check constraint


def test_remove_deactivates_only_own_samples_of_that_model(world):
    one(world, "s1", ADD, emb(512, 0.2), "onnx-w600k_mbf", None)
    assert one(world, "s1", "select remove_face_samples('dlib-resnet-128')") == 1
    assert run(world, "s1", "select * from my_face_sample_counts()") == [("onnx-w600k_mbf", 1)]
    assert one(world, "super", "select count(*) from face_profiles where student_id=2 and is_active") == 1    # s2 untouched
    assert one(world, "super", "select count(*) from face_profiles where student_id=1 and not is_active") == 1  # soft-deleted, not erased
    assert code(world, "t1", "select remove_face_samples('dlib-resnet-128')") == "PT403"


def test_embeddings_stay_private_but_teacher_gallery_is_model_filterable(world):
    one(world, "s1", ADD, emb(512, 0.2), "onnx-w600k_mbf", None)
    assert count(world, "s1", "face_profiles") == 0                                      # students cannot read templates, even their own
    assert run(world, "s2", "select * from my_face_sample_counts()") == [("dlib-resnet-128", 1)]   # counts are own-only
    rows = run(world, "t1", "select student_id from face_profiles where is_active and model='onnx-w600k_mbf'")
    assert rows == [(1,)]
    assert run(world, "t2", "select student_id from face_profiles where model='onnx-w600k_mbf'") == []    # not t2's student
