-- SnapClass schema, migration 0001 (clean install; no legacy data is migrated).
-- Run in the Supabase SQL editor, or: psql "$DATABASE_URL" -f supabase/migrations/0001_init.sql
--
-- SECURITY MODEL (until Phase 3):
--   * RLS is ENABLED on every table with NO policies, and anon/authenticated are revoked,
--     so the public anon key can read/write NOTHING.
--   * The Streamlit server must use the SERVICE ROLE key (server-side only, never in a browser).
--   * Mutations go through the functions below, which enforce ownership + write audit_logs.
--   * Phase 3 replaces the p_teacher_id parameters with auth.uid()-based policies.

create or replace function set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

-- ───────────── people ─────────────
create table teachers (
  teacher_id    bigint generated always as identity primary key,
  username      text not null check (username = lower(username) and char_length(username) between 3 and 40),
  password_hash text not null,
  name          text not null check (char_length(btrim(name)) > 0),
  is_active     boolean not null default true,
  auth_user_id  uuid unique,                       -- linked to Supabase Auth in Phase 3
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index teachers_username_uidx on teachers (username);

create table students (
  student_id   bigint generated always as identity primary key,
  name         text not null check (char_length(btrim(name)) > 0),
  roll_number  text,
  email        text,
  phone        text,
  is_active    boolean not null default true,
  auth_user_id uuid unique,                        -- linked to Supabase Auth in Phase 3
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index students_roll_uidx  on students (lower(roll_number)) where roll_number is not null;
create unique index students_email_uidx on students (lower(email))       where email is not null;

-- Biometric templates (sensitive). Many face samples per student; one active voice profile.
create table face_profiles (
  profile_id    bigint generated always as identity primary key,
  student_id    bigint not null references students(student_id) on delete cascade,
  embedding     jsonb  not null check (jsonb_typeof(embedding) = 'array' and jsonb_array_length(embedding) between 64 and 1024),
  model         text   not null default 'dlib-resnet-128',
  quality_score real   check (quality_score between 0 and 100),
  is_active     boolean not null default true,
  created_at    timestamptz not null default now()
);
create index face_profiles_student_idx on face_profiles (student_id) where is_active;

create table voice_profiles (
  profile_id bigint generated always as identity primary key,
  student_id bigint not null references students(student_id) on delete cascade,
  embedding  jsonb  not null check (jsonb_typeof(embedding) = 'array' and jsonb_array_length(embedding) between 64 and 1024),
  model      text   not null default 'resemblyzer',
  is_active  boolean not null default true,
  created_at timestamptz not null default now()
);
create unique index voice_profiles_one_active_uidx on voice_profiles (student_id) where is_active;

-- ───────────── academic ─────────────
create table subjects (
  subject_id   bigint generated always as identity primary key,
  subject_code text not null check (char_length(btrim(subject_code)) between 2 and 32),
  name         text not null check (char_length(btrim(name)) > 0),
  section      text not null check (char_length(btrim(section)) > 0),
  teacher_id   bigint not null references teachers(teacher_id) on delete restrict,   -- owner / creator
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index subjects_code_uidx on subjects (lower(subject_code));
create index subjects_teacher_idx on subjects (teacher_id);

create table enrollments (
  enrollment_id bigint generated always as identity primary key,
  student_id    bigint not null references students(student_id) on delete cascade,
  subject_id    bigint not null references subjects(subject_id) on delete cascade,
  enrolled_at   timestamptz not null default now(),
  unique (student_id, subject_id)                  -- no double enrolment
);
create index enrollments_subject_idx on enrollments (subject_id);

-- ───────────── attendance ─────────────
create table attendance_sessions (
  session_id  bigint generated always as identity primary key,
  subject_id  bigint not null references subjects(subject_id) on delete restrict,
  teacher_id  bigint not null references teachers(teacher_id) on delete restrict,
  method      text   not null check (method in ('FACE','VOICE','FACE_PLUS_VOICE','MANUAL')),
  status      text   not null default 'OPEN' check (status in ('OPEN','COMPLETED','CANCELLED')),
  location    text,
  started_at  timestamptz not null default now(),
  ended_at    timestamptz,
  created_by  bigint not null references teachers(teacher_id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (ended_at is null or ended_at >= started_at),
  check ((status = 'OPEN') = (ended_at is null))
);
create index attendance_sessions_subject_idx on attendance_sessions (subject_id, started_at desc);
create index attendance_sessions_teacher_idx on attendance_sessions (teacher_id, started_at desc);
create unique index one_open_session_per_subject on attendance_sessions (subject_id) where status = 'OPEN';

-- "MANUALLY_CORRECTED" is the flag manually_corrected (status keeps the real present/absent meaning).
create table attendance_records (
  record_id          bigint generated always as identity primary key,
  session_id         bigint not null references attendance_sessions(session_id) on delete cascade,
  student_id         bigint not null references students(student_id) on delete restrict,
  status             text   not null check (status in ('PRESENT','LATE','ABSENT','EXCUSED','UNKNOWN','REJECTED')),
  reason             text,
  source             text,
  confidence         real check (confidence between 0 and 1),
  manually_corrected boolean not null default false,
  marked_by          bigint references teachers(teacher_id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (session_id, student_id)                  -- no duplicate record per student/session
);
create index attendance_records_student_idx on attendance_records (student_id);

create table attendance_corrections (
  correction_id bigint generated always as identity primary key,
  record_id     bigint not null references attendance_records(record_id) on delete cascade,
  old_status    text not null,
  new_status    text not null,
  old_reason    text,
  reason        text not null check (char_length(btrim(reason)) > 0),
  corrected_by  bigint not null references teachers(teacher_id),
  created_at    timestamptz not null default now(),
  reverted_at   timestamptz,
  reverted_by   bigint references teachers(teacher_id)
);
create index attendance_corrections_record_idx on attendance_corrections (record_id);

create table audit_logs (
  audit_id    bigint generated always as identity primary key,
  actor_role  text not null,
  actor_id    bigint,
  action      text not null,
  entity_type text not null,
  entity_id   text,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index audit_logs_entity_idx  on audit_logs (entity_type, entity_id);
create index audit_logs_created_idx on audit_logs (created_at desc);

create or replace function audit_logs_append_only() returns trigger language plpgsql as $$
begin raise exception 'audit_logs is append-only' using errcode = 'PT403'; end $$;
create trigger audit_logs_no_update before update or delete on audit_logs
  for each row execute function audit_logs_append_only();

-- updated_at triggers
create trigger t_upd before update on teachers            for each row execute function set_updated_at();
create trigger t_upd before update on students            for each row execute function set_updated_at();
create trigger t_upd before update on subjects            for each row execute function set_updated_at();
create trigger t_upd before update on attendance_sessions for each row execute function set_updated_at();
create trigger t_upd before update on attendance_records  for each row execute function set_updated_at();

-- ───────────── functions (SQLSTATE PT4xx => PostgREST returns that HTTP status) ─────────────
create or replace function write_audit(p_role text, p_actor bigint, p_action text, p_type text, p_id text, p_details jsonb default '{}')
returns void language sql as $$
  insert into audit_logs(actor_role, actor_id, action, entity_type, entity_id, details) values (p_role, p_actor, p_action, p_type, p_id, p_details);
$$;

create or replace function require_teacher(p_teacher_id bigint) returns void language plpgsql as $$
begin
  if not exists (select 1 from teachers where teacher_id = p_teacher_id and is_active) then
    raise exception 'teacher not found or inactive' using errcode = 'PT403';
  end if;
end $$;

create or replace function register_student(p_name text, p_face jsonb, p_voice jsonb default null, p_face_quality real default null)
returns bigint language plpgsql as $$
declare v_id bigint;
begin
  if p_name is null or btrim(p_name) = '' then raise exception 'name required' using errcode = 'PT422'; end if;
  insert into students(name) values (btrim(p_name)) returning student_id into v_id;
  if p_face  is not null then insert into face_profiles(student_id, embedding, quality_score) values (v_id, p_face, p_face_quality); end if;
  if p_voice is not null then insert into voice_profiles(student_id, embedding) values (v_id, p_voice); end if;
  perform write_audit('SYSTEM', null, 'student.registered', 'student', v_id::text, jsonb_build_object('has_face', p_face is not null, 'has_voice', p_voice is not null));
  return v_id;
end $$;

create or replace function create_attendance_session(p_subject_id bigint, p_teacher_id bigint, p_method text, p_location text default null)
returns bigint language plpgsql as $$
declare v_owner bigint; v_id bigint;
begin
  perform require_teacher(p_teacher_id);
  select teacher_id into v_owner from subjects where subject_id = p_subject_id;
  if not found then raise exception 'subject not found' using errcode = 'PT404'; end if;
  if v_owner <> p_teacher_id then raise exception 'not your subject' using errcode = 'PT403'; end if;
  if exists (select 1 from attendance_sessions where subject_id = p_subject_id and status = 'OPEN') then
    raise exception 'an open session already exists for this subject' using errcode = 'PT409';
  end if;
  insert into attendance_sessions(subject_id, teacher_id, method, location, created_by)
  values (p_subject_id, p_teacher_id, p_method, nullif(btrim(p_location), ''), p_teacher_id) returning session_id into v_id;
  perform write_audit('TEACHER', p_teacher_id, 'session.created', 'attendance_session', v_id::text, jsonb_build_object('subject_id', p_subject_id, 'method', p_method));
  return v_id;
end $$;

create or replace function complete_attendance_session(p_session_id bigint, p_teacher_id bigint, p_records jsonb)
returns integer language plpgsql as $$
declare s attendance_sessions%rowtype; n integer;
begin
  perform require_teacher(p_teacher_id);
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> p_teacher_id then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'OPEN' then raise exception 'session is not open' using errcode = 'PT409'; end if;
  if p_records is null or jsonb_typeof(p_records) <> 'array' then raise exception 'records must be an array' using errcode = 'PT422'; end if;
  if exists (
    select 1 from jsonb_to_recordset(p_records) as r(student_id bigint)
    where not exists (select 1 from enrollments e where e.student_id = r.student_id and e.subject_id = s.subject_id)
  ) then raise exception 'record for a student not enrolled in this subject' using errcode = 'PT422'; end if;

  insert into attendance_records(session_id, student_id, status, source, confidence, marked_by)
  select p_session_id, r.student_id, r.status, r.source, r.confidence, p_teacher_id
  from jsonb_to_recordset(p_records) as r(student_id bigint, status text, source text, confidence real)
  on conflict (session_id, student_id) do nothing;
  get diagnostics n = row_count;

  update attendance_sessions set status = 'COMPLETED', ended_at = now() where session_id = p_session_id;
  perform write_audit('TEACHER', p_teacher_id, 'session.completed', 'attendance_session', p_session_id::text, jsonb_build_object('records_inserted', n));
  return n;
end $$;

create or replace function cancel_attendance_session(p_session_id bigint, p_teacher_id bigint) returns void language plpgsql as $$
declare s attendance_sessions%rowtype;
begin
  perform require_teacher(p_teacher_id);
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> p_teacher_id then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'OPEN' then raise exception 'only an open session can be cancelled' using errcode = 'PT409'; end if;
  update attendance_sessions set status = 'CANCELLED', ended_at = now() where session_id = p_session_id;
  perform write_audit('TEACHER', p_teacher_id, 'session.cancelled', 'attendance_session', p_session_id::text);
end $$;

create or replace function reopen_attendance_session(p_session_id bigint, p_teacher_id bigint) returns void language plpgsql as $$
declare s attendance_sessions%rowtype;
begin
  perform require_teacher(p_teacher_id);
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> p_teacher_id then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'COMPLETED' then raise exception 'only a completed session can be reopened' using errcode = 'PT409'; end if;
  if exists (select 1 from attendance_sessions where subject_id = s.subject_id and status = 'OPEN') then
    raise exception 'another session is already open for this subject' using errcode = 'PT409';
  end if;
  update attendance_sessions set status = 'OPEN', ended_at = null where session_id = p_session_id;
  perform write_audit('TEACHER', p_teacher_id, 'session.reopened', 'attendance_session', p_session_id::text);
end $$;

create or replace function correct_attendance_record(p_session_id bigint, p_student_id bigint, p_teacher_id bigint, p_new_status text, p_reason text)
returns bigint language plpgsql as $$
declare s attendance_sessions%rowtype; r attendance_records%rowtype; v_id bigint;
begin
  perform require_teacher(p_teacher_id);
  select * into s from attendance_sessions where session_id = p_session_id;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> p_teacher_id then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status = 'CANCELLED' then raise exception 'cancelled sessions cannot be edited' using errcode = 'PT409'; end if;
  if p_reason is null or btrim(p_reason) = '' then raise exception 'a reason is required' using errcode = 'PT422'; end if;
  if p_new_status not in ('PRESENT','LATE','ABSENT','EXCUSED') then raise exception 'invalid status for a correction' using errcode = 'PT422'; end if;
  select * into r from attendance_records where session_id = p_session_id and student_id = p_student_id for update;
  if not found then raise exception 'record not found' using errcode = 'PT404'; end if;
  if r.status = p_new_status then raise exception 'status is unchanged' using errcode = 'PT422'; end if;

  insert into attendance_corrections(record_id, old_status, new_status, old_reason, reason, corrected_by)
  values (r.record_id, r.status, p_new_status, r.reason, btrim(p_reason), p_teacher_id) returning correction_id into v_id;
  update attendance_records set status = p_new_status, reason = btrim(p_reason), manually_corrected = true where record_id = r.record_id;
  perform write_audit('TEACHER', p_teacher_id, 'attendance.corrected', 'attendance_record', r.record_id::text,
                      jsonb_build_object('from', r.status, 'to', p_new_status, 'reason', btrim(p_reason), 'session_id', p_session_id));
  return v_id;
end $$;

create or replace function undo_attendance_correction(p_correction_id bigint, p_teacher_id bigint) returns void language plpgsql as $$
declare c attendance_corrections%rowtype; s attendance_sessions%rowtype; v_latest bigint;
begin
  perform require_teacher(p_teacher_id);
  select * into c from attendance_corrections where correction_id = p_correction_id for update;
  if not found then raise exception 'correction not found' using errcode = 'PT404'; end if;
  select s2.* into s from attendance_sessions s2 join attendance_records r on r.session_id = s2.session_id where r.record_id = c.record_id;
  if s.teacher_id <> p_teacher_id then raise exception 'not your session' using errcode = 'PT403'; end if;
  if c.reverted_at is not null then raise exception 'already undone' using errcode = 'PT409'; end if;
  select max(correction_id) into v_latest from attendance_corrections where record_id = c.record_id and reverted_at is null;
  if v_latest <> c.correction_id then raise exception 'only the latest correction can be undone' using errcode = 'PT409'; end if;

  update attendance_records set status = c.old_status, reason = c.old_reason,
         manually_corrected = exists (select 1 from attendance_corrections x where x.record_id = c.record_id and x.reverted_at is null and x.correction_id <> c.correction_id)
   where record_id = c.record_id;
  update attendance_corrections set reverted_at = now(), reverted_by = p_teacher_id where correction_id = c.correction_id;
  perform write_audit('TEACHER', p_teacher_id, 'attendance.correction_undone', 'attendance_record', c.record_id::text,
                      jsonb_build_object('correction_id', c.correction_id, 'restored', c.old_status));
end $$;

-- ───────────── lock-down ─────────────
alter table teachers               enable row level security;
alter table students               enable row level security;
alter table face_profiles          enable row level security;
alter table voice_profiles         enable row level security;
alter table subjects               enable row level security;
alter table enrollments            enable row level security;
alter table attendance_sessions    enable row level security;
alter table attendance_records     enable row level security;
alter table attendance_corrections enable row level security;
alter table audit_logs             enable row level security;

revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
grant  all on all tables    in schema public to service_role;
grant  all on all sequences in schema public to service_role;
grant  execute on all functions in schema public to service_role;
