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

## Phase 4 tests
`test_attendance_math.py` (exact arithmetic vs brute force), `test_db_analytics.py` (views/functions/RLS), `test_dashboard_service.py` (aggregation, ordering, timezone boundary, ownership), `test_ui_dashboards.py` + updated `test_ui_auth.py`/`test_ui_teacher.py` (AppTest), and `test_integration_stack.py::test_dashboards_end_to_end_with_isolation` (real JWT/PostgREST/RLS). Run everything with: `eval "$(sh scripts/test_stack.sh | grep '^export')" && pytest -q` (start the stack and pytest in the same command).

## Phase 5 tests
`test_face_matching.py` (metric-aware matching, margin, top-k, scale invariance, dimension mismatch), `test_recognition_service.py` (fake engine: multi-photo, unknown/ambiguous/too-small/no-face reporting, model filtering), `test_face_engines.py` (real dlib + ONNX engines on skimage's astronaut photo; skipped if models are missing; set `ONNX_MODEL_DIR`), `test_db_face_samples.py` (migration 0004), plus an end-to-end test in `test_integration_stack.py`.

## Phase 6 tests
`tests/test_face_quality_liveness.py`: metrics on a real photo with injected blur/dark/bright defects, monotonic blur score, edge cases (degenerate/outside boxes), enrolment gate, quality stored with samples, liveness geometry/identity/duplicate/missing-photo failures, switch-off, and the classroom LOW_QUALITY path.

## Phase 7 tests
`test_voice_quality.py` (synthetic audio: clean, short, quiet, clipped, noisy, silent, NaN; segmentation gap/blip/window rules), `test_voice_service.py` (fake encoder: recognised/unknown/ambiguous/noisy/back-to-back speakers/no templates/back-compat/enrolment gate), `test_db_voice_samples.py` (0005 on real PostgreSQL: quota, validation, audit, isolation).

## Phase 8 tests
`test_fusion_service.py` (every fusion rule, policies, weight, notes, one record per student) and `test_integration_stack.py::test_fused_face_plus_voice_session_is_saved_with_source_and_confidence` (real DB).

## Phase 9 tests
`test_forecast.py` (brute-force probability check, boundary, risk ordering, recency, backtest calibration), `test_trends.py`, `test_anomalies.py` (each detector with positive and negative cases, no input mutation), `test_db_recognition_stats.py` (0006 whitelist/ownership), `test_ui_analytics.py` (charts, teacher/student/admin pages), and `test_integration_stack.py::test_analytics_end_to_end_with_isolation` (real JWT/RLS).

## Phase 10 tests
`test_assistant.py` (schema validation incl. NaN/bool/unknown keys, role gates, identity-from-principal, subject resolution, routing, exact answers, rate limit, scripted-LLM loop incl. cross-role/injection attempts and bounded rounds, Anthropic adapter with a fake module, safe error text), `test_ui_assistant.py` (chat panel, logout clears history), and `test_integration_stack.py::test_assistant_answers_are_scoped_by_the_database`.
