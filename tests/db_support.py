"""Shared helpers + fixtures for the real-PostgreSQL tests (schema, RLS, analytics).

Supabase's `auth` schema is simulated (auth.users + auth.uid() reading request.jwt.claims, as PostgREST sets it)."""
import json
import os
import pathlib
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql  # noqa: E402

URL = os.environ.get("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")
MIGRATIONS = sorted((pathlib.Path(__file__).resolve().parents[1] / "supabase" / "migrations").glob("*.sql"))
TABLES = ["audit_logs", "attendance_corrections", "attendance_records", "attendance_sessions", "enrollments",
          "subjects", "voice_profiles", "face_profiles", "profiles", "students", "teachers"]

AUTH_SHIM = """
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key default gen_random_uuid(), email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
"""
USERS = ["t1", "t2", "tpend", "s1", "s2", "s3", "s4", "admin"]
UID = {name: str(uuid.uuid5(uuid.NAMESPACE_DNS, name)) for name in USERS}


@pytest.fixture(scope="module")
def dsn():
    admin = psycopg2.connect(URL); admin.autocommit = True
    cur = admin.cursor()
    for role, extra in (("anon", ""), ("authenticated", ""), ("service_role", "bypassrls")):
        cur.execute(f"do $$ begin create role {role} nologin {extra}; exception when duplicate_object then null; end $$")
    name = f"snap_{uuid.uuid4().hex[:8]}"
    cur.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    test_dsn = f"{URL.rsplit('/', 1)[0]}/{name}"
    c = psycopg2.connect(test_dsn); c.autocommit = True
    c.cursor().execute(AUTH_SHIM)
    for m in MIGRATIONS:
        c.cursor().execute(m.read_text())
    c.close()
    yield test_dsn
    cur.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))
    admin.close()


@pytest.fixture
def db(dsn):
    conn = psycopg2.connect(dsn); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("truncate " + ", ".join(TABLES) + " restart identity cascade; truncate auth.users cascade")
    yield cur
    cur.execute("reset role")
    conn.close()


def _ctx(cur, who):
    cur.execute("reset role")
    if who is None:
        cur.execute("select set_config('request.jwt.claims', '', false)"); cur.execute("set role anon")
    elif who == "service":
        cur.execute("set role service_role")
    elif who == "super":
        pass
    else:
        cur.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps({"sub": UID[who], "role": "authenticated"}),))
        cur.execute("set role authenticated")


def run(cur, who, q, *a):
    _ctx(cur, who)
    try:
        cur.execute(q, a)
        return cur.fetchall() if cur.description else None
    finally:
        cur.execute("reset role")


def one(cur, who, q, *a):
    return run(cur, who, q, *a)[0][0]


def code(cur, who, q, *a):
    """Statement must fail; return its SQLSTATE."""
    with pytest.raises(psycopg2.Error) as ei:
        run(cur, who, q, *a)
    return ei.value.pgcode


def count(cur, who, table):
    return one(cur, who, f"select count(*) from {table}")


def emb(n=128, v=0.1):
    return json.dumps([v] * n)


@pytest.fixture
def world(db):
    """t1/t2 active teachers, tpend inactive teacher, students s1-s3 enrolled in t1's DSA1, s4 outsider, one admin."""
    for u in USERS:
        run(db, "super", "insert into auth.users(id, email) values (%s, %s)", UID[u], f"{u}@x.com")
    run(db, "super", "select provision_account(%s,'ADMIN','Root','admin@x.com')", UID["admin"])
    for u in ("t1", "t2"):
        run(db, "super", "select provision_account(%s,'TEACHER',%s,%s,true)", UID[u], u.upper(), f"{u}@x.com")
    run(db, "super", "select provision_account(%s,'TEACHER','Pending','tpend@x.com',false)", UID["tpend"])
    for i, u in enumerate(("s1", "s2", "s3", "s4"), 1):
        run(db, "super", "select provision_account(%s,'STUDENT',%s,%s,true,%s,%s,%s)", UID[u], u.upper(), f"{u}@x.com", f"R{i}", emb(128, i / 10), emb(256, i / 10) if u != "s3" else None)
    run(db, "super", "insert into subjects(subject_code,name,section,teacher_id) values ('DSA1','DSA','A',1), ('OS1','OS','B',2)")
    for s in (1, 2, 3):
        run(db, "super", "insert into enrollments(student_id, subject_id) values (%s,1)", s)
    run(db, "super", "insert into enrollments(student_id, subject_id) values (4,2)")       # s4 belongs to t2's OS1
    return db


def new_session(db, who="t1", subject=1, method="FACE"):
    return one(db, who, "select create_attendance_session(%s,%s)", subject, method)


def recs(*rows):
    return json.dumps([{"student_id": s, "status": st, "source": "Photo 1"} for s, st in rows])
