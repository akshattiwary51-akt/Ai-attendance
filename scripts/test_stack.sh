#!/bin/sh
# Bring up a throw-away PostgreSQL + PostgREST stack for the database-backed tests (Linux, run as root).
#   sh scripts/test_stack.sh      → prints the env vars to export
# Installs postgresql via apt and downloads PostgREST if they are missing. Safe to re-run: it rebuilds the test DB.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGRST_VER=v12.2.3
SECRET="test-secret-test-secret-test-secret-123456"
command -v pg_ctlcluster >/dev/null || { apt-get update -q >/dev/null && apt-get install -y -q postgresql >/dev/null; }
VER=$(ls /usr/lib/postgresql | sort -n | tail -1)
pg_ctlcluster "$VER" main status >/dev/null 2>&1 || pg_ctlcluster "$VER" main start
sleep 2
if [ ! -x /tmp/postgrest ]; then
  curl -sL -o /tmp/pgrst.tar.xz "https://github.com/PostgREST/postgrest/releases/download/$PGRST_VER/postgrest-$PGRST_VER-linux-static-x64.tar.xz"
  tar -xf /tmp/pgrst.tar.xz -C /tmp
fi
pkill postgrest 2>/dev/null || true; sleep 1
su postgres -c "psql -q -c \"alter user postgres password 'pw'\""
for r in "anon" "authenticated" "service_role bypassrls"; do
  su postgres -c "psql -q -c \"do \\\$\\\$ begin create role $r nologin; exception when duplicate_object then null; end \\\$\\\$;\""
done
su postgres -c "psql -q -c 'drop database if exists snapclass_test with (force)' -c 'create database snapclass_test'"
cat > /tmp/shim.sql <<'SQL'
create schema auth;
create table auth.users (id uuid primary key default gen_random_uuid(), email text);
create function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''), (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
SQL
chmod 644 /tmp/shim.sql
su postgres -c "psql -d snapclass_test -q -v ON_ERROR_STOP=1 -f /tmp/shim.sql"
for f in "$ROOT"/supabase/migrations/*.sql; do su postgres -c "psql -d snapclass_test -q -v ON_ERROR_STOP=1 -f $f"; done
su postgres -c "psql -d snapclass_test -q -c 'grant anon, authenticated, service_role to postgres' -c 'grant usage on schema public to anon, authenticated, service_role'" 2>/dev/null || true
cat > /tmp/pgrst.conf <<CONF
db-uri = "postgres://postgres:pw@localhost:5432/snapclass_test"
db-schemas = "public"
db-anon-role = "anon"
jwt-secret = "$SECRET"
server-port = 3111
db-max-rows = 1000
CONF
nohup /tmp/postgrest /tmp/pgrst.conf > /tmp/pgrst.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "postgrest (anon, no JWT) HTTP %{http_code} (401 expected)\n" localhost:3111/students
cat <<ENV
export TEST_DATABASE_URL=postgresql://postgres:pw@localhost/postgres
export TEST_POSTGREST_URL=http://localhost:3111
export TEST_POSTGREST_DSN=postgresql://postgres:pw@localhost/snapclass_test
export TEST_JWT_SECRET=$SECRET
ENV
