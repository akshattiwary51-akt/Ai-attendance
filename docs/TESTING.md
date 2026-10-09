# Testing

`pytest` runs everything that needs no external services (unit, service and Streamlit `AppTest` UI tests).
Two groups need PostgreSQL and are **skipped unless their env vars are set**:

| Suite | Env vars | What it proves |
|---|---|---|
| `tests/test_db_schema.py` | `TEST_DATABASE_URL=postgresql://postgres:PW@localhost/postgres` (superuser; a throw-away DB is created/dropped) | constraints, DB functions, audit trail, RLS lock-down, atomicity |
| `tests/test_integration_stack.py` | `TEST_POSTGREST_URL`, `TEST_POSTGREST_DSN`, `TEST_JWT_SECRET` | services → repositories → **PostgREST with real JWTs** → PostgreSQL + RLS, as distinct admin/teacher/student users (incl. the 1000-row cap) |

## Recipe for the integration stack (Linux)
Supabase's `auth` schema is simulated locally (`auth.users`, `auth.uid()` reading `request.jwt.claims`, exactly how PostgREST/GoTrue expose it).
```bash
sudo apt-get install postgresql                       # or any PostgreSQL 14+
createdb snapclass_test
psql -d snapclass_test -c "create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;"
psql -d snapclass_test -c "create schema auth; create table auth.users (id uuid primary key default gen_random_uuid(), email text);
  create function auth.uid() returns uuid language sql stable as \$\$ select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''), (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid \$\$;
  grant usage on schema auth to anon, authenticated, service_role; grant execute on function auth.uid() to anon, authenticated, service_role;"
for f in supabase/migrations/*.sql; do psql -d snapclass_test -v ON_ERROR_STOP=1 -f $f; done
psql -d snapclass_test -c "grant usage on schema public to anon, authenticated, service_role"
# PostgREST (https://github.com/PostgREST/postgrest/releases), config:
#   db-uri="postgres://postgres:PW@localhost/snapclass_test"  db-schemas="public"  db-anon-role="anon"
#   jwt-secret="<32+ chars>"  server-port=3111
TEST_DATABASE_URL=postgresql://postgres:PW@localhost/postgres \
TEST_POSTGREST_URL=http://localhost:3111 TEST_POSTGREST_DSN=postgresql://postgres:PW@localhost/snapclass_test TEST_JWT_SECRET=<same secret> pytest
```
Note: PostgREST tolerates 30 s of clock skew on JWT `exp`.

Not covered by automated tests: **GoTrue / Supabase Auth itself** (sign-up, sign-in, refresh, email confirmation are exercised only through a fake provider; `SupabaseAuthProvider` is a thin wrapper verified against the library's API surface, not a live project), dlib / Resemblyzer inference, the browser camera/microphone widgets, and hosted-Supabase specifics (tested against vanilla PostgREST 12).
