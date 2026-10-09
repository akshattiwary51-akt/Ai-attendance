-- SnapClass migration 0002: Supabase Auth identities, roles and Row Level Security.
-- Requires 0001. Run after it in the Supabase SQL editor.
--
-- MODEL
--   * Identity = auth.uid() (Supabase Auth JWT). `profiles` maps it to ONE role + teacher/student row.
--   * The app talks to the database AS THE LOGGED-IN USER (anon key + user JWT) so RLS is the enforcement point.
--   * Writes happen only through SECURITY DEFINER functions that derive the caller from auth.uid()
--     (no caller-supplied teacher/student ids are trusted) and write audit_logs.
--   * The service-role key is used server-side ONLY for account provisioning (provision_account).
--   * Policies never sub-select RLS-protected tables directly (that recurses); they call the
--     private.* SECURITY DEFINER helpers instead. `private` is not exposed through the API.

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated, service_role;

-- ───────────── password-era columns go away; Supabase Auth owns credentials ─────────────
alter table teachers drop column if exists username, drop column if exists password_hash, drop column if exists auth_user_id;
alter table students drop column if exists auth_user_id;
alter table teachers add column if not exists email text;
update teachers set email = 'legacy-' || teacher_id || '@invalid.local' where email is null;
alter table teachers alter column email set not null;
create unique index if not exists teachers_email_uidx on teachers (lower(email));
alter table audit_logs add column if not exists actor_user_id uuid;

create table profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  role       text not null check (role in ('ADMIN','TEACHER','STUDENT')),
  teacher_id bigint unique references teachers(teacher_id) on delete cascade,
  student_id bigint unique references students(student_id) on delete cascade,
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((role = 'TEACHER' and teacher_id is not null and student_id is null)
      or (role = 'STUDENT' and student_id is not null and teacher_id is null)
      or (role = 'ADMIN'   and teacher_id is null     and student_id is null))
);
create trigger t_upd before update on profiles for each row execute function set_updated_at();
alter table profiles enable row level security;

-- ───────────── identity + membership helpers (SECURITY DEFINER; bypass RLS, no recursion) ─────────────
create function private.app_role() returns text language sql stable security definer set search_path = public, pg_temp as $$
  select role from profiles where user_id = auth.uid() and is_active $$;
create function private.is_admin() returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select coalesce((select role = 'ADMIN' from profiles where user_id = auth.uid() and is_active), false) $$;
create function private.teacher_id() returns bigint language sql stable security definer set search_path = public, pg_temp as $$
  select teacher_id from profiles where user_id = auth.uid() and is_active and role = 'TEACHER' $$;
create function private.student_id() returns bigint language sql stable security definer set search_path = public, pg_temp as $$
  select student_id from profiles where user_id = auth.uid() and is_active and role = 'STUDENT' $$;

create function private.require_teacher() returns bigint language plpgsql stable security definer set search_path = public, pg_temp as $$
declare v bigint := private.teacher_id();
begin if v is null then raise exception 'teacher access required' using errcode = 'PT403'; end if; return v; end $$;
create function private.require_student() returns bigint language plpgsql stable security definer set search_path = public, pg_temp as $$
declare v bigint := private.student_id();
begin if v is null then raise exception 'student access required' using errcode = 'PT403'; end if; return v; end $$;
create function private.require_admin() returns void language plpgsql stable security definer set search_path = public, pg_temp as $$
begin if not private.is_admin() then raise exception 'admin access required' using errcode = 'PT403'; end if; end $$;

create function private.teaches(p_subject_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from subjects where subject_id = p_subject_id and teacher_id = private.teacher_id()) $$;
create function private.enrolled_in(p_subject_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from enrollments where subject_id = p_subject_id and student_id = private.student_id()) $$;
create function private.teaches_student(p_student_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from enrollments e join subjects s using (subject_id) where e.student_id = p_student_id and s.teacher_id = private.teacher_id()) $$;
create function private.owns_session(p_session_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from attendance_sessions where session_id = p_session_id and teacher_id = private.teacher_id()) $$;
create function private.has_record_in_session(p_session_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from attendance_records where session_id = p_session_id and student_id = private.student_id()) $$;
create function private.owns_record(p_record_id bigint) returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from attendance_records r join attendance_sessions s using (session_id) where r.record_id = p_record_id and s.teacher_id = private.teacher_id()) $$;

create function private.audit(p_action text, p_type text, p_id text, p_details jsonb default '{}')
returns void language sql security definer set search_path = public, pg_temp as $$
  insert into audit_logs(actor_role, actor_id, actor_user_id, action, entity_type, entity_id, details)
  values (coalesce(private.app_role(), 'SYSTEM'), coalesce(private.teacher_id(), private.student_id()), auth.uid(), p_action, p_type, p_id, p_details) $$;

-- ───────────── drop the Phase-2 functions that trusted caller-supplied ids ─────────────
drop function if exists create_attendance_session(bigint, bigint, text, text);
drop function if exists complete_attendance_session(bigint, bigint, jsonb);
drop function if exists cancel_attendance_session(bigint, bigint);
drop function if exists reopen_attendance_session(bigint, bigint);
drop function if exists correct_attendance_record(bigint, bigint, bigint, text, text);
drop function if exists undo_attendance_correction(bigint, bigint);
drop function if exists register_student(text, jsonb, jsonb, real);
drop function if exists require_teacher(bigint);
drop function if exists write_audit(text, bigint, text, text, text, jsonb);

-- ───────────── user-facing functions (caller identity comes from auth.uid()) ─────────────
create function create_attendance_session(p_subject_id bigint, p_method text, p_location text default null)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); v_owner bigint; v_id bigint;
begin
  select teacher_id into v_owner from subjects where subject_id = p_subject_id;
  if not found then raise exception 'subject not found' using errcode = 'PT404'; end if;
  if v_owner <> v_tid then raise exception 'not your subject' using errcode = 'PT403'; end if;
  if exists (select 1 from attendance_sessions where subject_id = p_subject_id and status = 'OPEN') then
    raise exception 'an open session already exists for this subject' using errcode = 'PT409';
  end if;
  insert into attendance_sessions(subject_id, teacher_id, method, location, created_by)
  values (p_subject_id, v_tid, p_method, nullif(btrim(p_location), ''), v_tid) returning session_id into v_id;
  perform private.audit('session.created', 'attendance_session', v_id::text, jsonb_build_object('subject_id', p_subject_id, 'method', p_method));
  return v_id;
end $$;

create function complete_attendance_session(p_session_id bigint, p_records jsonb)
returns integer language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); s attendance_sessions%rowtype; n integer;
begin
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'OPEN' then raise exception 'session is not open' using errcode = 'PT409'; end if;
  if p_records is null or jsonb_typeof(p_records) <> 'array' then raise exception 'records must be an array' using errcode = 'PT422'; end if;
  if exists (select 1 from jsonb_to_recordset(p_records) as r(student_id bigint)
             where not exists (select 1 from enrollments e where e.student_id = r.student_id and e.subject_id = s.subject_id))
  then raise exception 'record for a student not enrolled in this subject' using errcode = 'PT422'; end if;

  insert into attendance_records(session_id, student_id, status, source, confidence, marked_by)
  select p_session_id, r.student_id, r.status, r.source, r.confidence, v_tid
  from jsonb_to_recordset(p_records) as r(student_id bigint, status text, source text, confidence real)
  on conflict (session_id, student_id) do nothing;
  get diagnostics n = row_count;
  update attendance_sessions set status = 'COMPLETED', ended_at = now() where session_id = p_session_id;
  perform private.audit('session.completed', 'attendance_session', p_session_id::text, jsonb_build_object('records_inserted', n));
  return n;
end $$;

create function cancel_attendance_session(p_session_id bigint) returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); s attendance_sessions%rowtype;
begin
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'OPEN' then raise exception 'only an open session can be cancelled' using errcode = 'PT409'; end if;
  update attendance_sessions set status = 'CANCELLED', ended_at = now() where session_id = p_session_id;
  perform private.audit('session.cancelled', 'attendance_session', p_session_id::text);
end $$;

create function reopen_attendance_session(p_session_id bigint) returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); s attendance_sessions%rowtype;
begin
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'COMPLETED' then raise exception 'only a completed session can be reopened' using errcode = 'PT409'; end if;
  if exists (select 1 from attendance_sessions where subject_id = s.subject_id and status = 'OPEN') then
    raise exception 'another session is already open for this subject' using errcode = 'PT409';
  end if;
  update attendance_sessions set status = 'OPEN', ended_at = null where session_id = p_session_id;
  perform private.audit('session.reopened', 'attendance_session', p_session_id::text);
end $$;

create function correct_attendance_record(p_session_id bigint, p_student_id bigint, p_new_status text, p_reason text)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); s attendance_sessions%rowtype; r attendance_records%rowtype; v_id bigint;
begin
  select * into s from attendance_sessions where session_id = p_session_id;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status = 'CANCELLED' then raise exception 'cancelled sessions cannot be edited' using errcode = 'PT409'; end if;
  if p_reason is null or btrim(p_reason) = '' then raise exception 'a reason is required' using errcode = 'PT422'; end if;
  if p_new_status not in ('PRESENT','LATE','ABSENT','EXCUSED') then raise exception 'invalid status for a correction' using errcode = 'PT422'; end if;
  select * into r from attendance_records where session_id = p_session_id and student_id = p_student_id for update;
  if not found then raise exception 'record not found' using errcode = 'PT404'; end if;
  if r.status = p_new_status then raise exception 'status is unchanged' using errcode = 'PT422'; end if;

  insert into attendance_corrections(record_id, old_status, new_status, old_reason, reason, corrected_by)
  values (r.record_id, r.status, p_new_status, r.reason, btrim(p_reason), v_tid) returning correction_id into v_id;
  update attendance_records set status = p_new_status, reason = btrim(p_reason), manually_corrected = true where record_id = r.record_id;
  perform private.audit('attendance.corrected', 'attendance_record', r.record_id::text,
         jsonb_build_object('from', r.status, 'to', p_new_status, 'reason', btrim(p_reason), 'session_id', p_session_id));
  return v_id;
end $$;

create function undo_attendance_correction(p_correction_id bigint) returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); c attendance_corrections%rowtype; v_owner bigint; v_latest bigint;
begin
  select * into c from attendance_corrections where correction_id = p_correction_id for update;
  if not found then raise exception 'correction not found' using errcode = 'PT404'; end if;
  select s.teacher_id into v_owner from attendance_records r join attendance_sessions s using (session_id) where r.record_id = c.record_id;
  if v_owner <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if c.reverted_at is not null then raise exception 'already undone' using errcode = 'PT409'; end if;
  select max(correction_id) into v_latest from attendance_corrections where record_id = c.record_id and reverted_at is null;
  if v_latest <> c.correction_id then raise exception 'only the latest correction can be undone' using errcode = 'PT409'; end if;

  update attendance_records set status = c.old_status, reason = c.old_reason,
         manually_corrected = exists (select 1 from attendance_corrections x where x.record_id = c.record_id and x.reverted_at is null and x.correction_id <> c.correction_id)
   where record_id = c.record_id;
  update attendance_corrections set reverted_at = now(), reverted_by = v_tid where correction_id = c.correction_id;
  perform private.audit('attendance.correction_undone', 'attendance_record', c.record_id::text,
         jsonb_build_object('correction_id', c.correction_id, 'restored', c.old_status));
end $$;

create function preview_subject(p_code text) returns jsonb language plpgsql stable security definer set search_path = public, pg_temp as $$
declare s subjects%rowtype;
begin
  if private.app_role() is null then raise exception 'login required' using errcode = 'PT403'; end if;
  select * into s from subjects where lower(subject_code) = lower(btrim(p_code));
  if not found then return null; end if;
  return jsonb_build_object('subject_id', s.subject_id, 'name', s.name, 'section', s.section,
                            'enrolled', exists (select 1 from enrollments where subject_id = s.subject_id and student_id = private.student_id()));
end $$;

create function enroll_by_code(p_code text) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_sid bigint := private.require_student(); s subjects%rowtype; n integer;
begin
  select * into s from subjects where lower(subject_code) = lower(btrim(p_code));
  if not found then return jsonb_build_object('outcome', 'NOT_FOUND'); end if;
  insert into enrollments(student_id, subject_id) values (v_sid, s.subject_id) on conflict (student_id, subject_id) do nothing;
  get diagnostics n = row_count;
  if n = 1 then perform private.audit('student.enrolled', 'subject', s.subject_id::text, jsonb_build_object('student_id', v_sid)); end if;
  return jsonb_build_object('outcome', case when n = 1 then 'ENROLLED' else 'ALREADY_ENROLLED' end,
                            'subject_id', s.subject_id, 'name', s.name, 'section', s.section);
end $$;

create function admin_set_active(p_role text, p_id bigint, p_active boolean) returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform private.require_admin();
  if p_role = 'TEACHER' then
    update teachers set is_active = p_active where teacher_id = p_id;
    update profiles set is_active = p_active where teacher_id = p_id;
  elsif p_role = 'STUDENT' then
    update students set is_active = p_active where student_id = p_id;
    update profiles set is_active = p_active where student_id = p_id;
  else raise exception 'role must be TEACHER or STUDENT' using errcode = 'PT422'; end if;
  if not found then raise exception 'user not found' using errcode = 'PT404'; end if;
  perform private.audit(case when p_active then 'user.activated' else 'user.deactivated' end, lower(p_role), p_id::text);
end $$;

-- Server-side only (service role): create the teacher/student/admin rows + profile for a new auth user.
create function provision_account(p_user_id uuid, p_role text, p_name text, p_email text, p_active boolean default true,
                                  p_roll_number text default null, p_face jsonb default null, p_voice jsonb default null, p_face_quality real default null)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id bigint;
begin
  if p_role = 'ADMIN' then
    insert into profiles(user_id, role) values (p_user_id, 'ADMIN');
    perform private.audit('account.provisioned', 'admin', p_user_id::text);
    return 0;
  end if;
  if p_name is null or btrim(p_name) = '' then raise exception 'name required' using errcode = 'PT422'; end if;
  if p_email is null or btrim(p_email) = '' then raise exception 'email required' using errcode = 'PT422'; end if;
  if p_role = 'TEACHER' then
    insert into teachers(name, email, is_active) values (btrim(p_name), lower(btrim(p_email)), p_active) returning teacher_id into v_id;
    insert into profiles(user_id, role, teacher_id, is_active) values (p_user_id, 'TEACHER', v_id, p_active);
  elsif p_role = 'STUDENT' then
    insert into students(name, email, roll_number, is_active) values (btrim(p_name), lower(btrim(p_email)), nullif(btrim(p_roll_number), ''), p_active) returning student_id into v_id;
    insert into profiles(user_id, role, student_id, is_active) values (p_user_id, 'STUDENT', v_id, p_active);
    if p_face  is not null then insert into face_profiles(student_id, embedding, quality_score) values (v_id, p_face, p_face_quality); end if;
    if p_voice is not null then insert into voice_profiles(student_id, embedding) values (v_id, p_voice); end if;
  else raise exception 'invalid role' using errcode = 'PT422'; end if;
  perform private.audit('account.provisioned', lower(p_role), v_id::text, jsonb_build_object('active', p_active, 'has_face', p_face is not null, 'has_voice', p_voice is not null));
  return v_id;
end $$;

-- ───────────── RLS policies (role: authenticated; anon has nothing) ─────────────
create policy profiles_read   on profiles for select to authenticated using (user_id = auth.uid() or private.is_admin());
create policy teachers_read   on teachers for select to authenticated using (teacher_id = private.teacher_id() or private.is_admin());
create policy students_read   on students for select to authenticated using (student_id = private.student_id() or private.is_admin() or private.teaches_student(student_id));
create policy face_read       on face_profiles  for select to authenticated using (private.teaches_student(student_id));
create policy voice_read      on voice_profiles for select to authenticated using (private.teaches_student(student_id));
create policy subjects_read   on subjects for select to authenticated using (teacher_id = private.teacher_id() or private.is_admin() or private.enrolled_in(subject_id));
create policy subjects_insert on subjects for insert to authenticated with check (teacher_id = private.teacher_id());
create policy enroll_read     on enrollments for select to authenticated using (student_id = private.student_id() or private.teaches(subject_id) or private.is_admin());
create policy enroll_delete   on enrollments for delete to authenticated using (student_id = private.student_id() or private.teaches(subject_id));
create policy sessions_read   on attendance_sessions for select to authenticated using (teacher_id = private.teacher_id() or private.is_admin() or private.has_record_in_session(session_id));
create policy records_read    on attendance_records  for select to authenticated using (student_id = private.student_id() or private.owns_session(session_id) or private.is_admin());
create policy corrections_read on attendance_corrections for select to authenticated using (private.owns_record(record_id) or private.is_admin());
create policy audit_read      on audit_logs for select to authenticated using (private.is_admin());

-- ───────────── privileges ─────────────
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public  from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon;

grant select on teachers, students, face_profiles, voice_profiles, subjects, enrollments, attendance_sessions,
                attendance_records, attendance_corrections, audit_logs, profiles to authenticated;
grant insert on subjects to authenticated;
grant delete on enrollments to authenticated;
grant usage on all sequences in schema public to authenticated;   -- subjects insert uses an identity column

grant execute on function create_attendance_session(bigint, text, text), complete_attendance_session(bigint, jsonb),
      cancel_attendance_session(bigint), reopen_attendance_session(bigint), correct_attendance_record(bigint, bigint, text, text),
      undo_attendance_correction(bigint), preview_subject(text), enroll_by_code(text), admin_set_active(text, bigint, boolean) to authenticated;
grant execute on all functions in schema private to authenticated, service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;   -- includes provision_account (service role ONLY)
