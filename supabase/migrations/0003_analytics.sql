-- SnapClass migration 0003: per-subject attendance target, RLS-respecting aggregation views, admin overview.
-- Requires 0001 + 0002.
--
-- Counting rules (single source of truth, mirrored in src/analytics/attendance_math.py):
--   attended  = PRESENT + LATE
--   conducted = PRESENT + LATE + ABSENT           (EXCUSED is neutral; UNKNOWN/REJECTED are never counted)
--   only COMPLETED sessions count (an open/reopened/cancelled session is excluded until confirmed)

alter table subjects add column target_percent numeric(5,2) not null default 75
  check (target_percent between 1 and 100);

-- security_invoker: the views run with the CALLER's privileges, so RLS on the base tables applies
-- (a student gets only their own rows, a teacher only their own subjects' rows, an admin everything).
create view v_subject_student_attendance with (security_invoker = true) as
select s.subject_id,
       r.student_id,
       count(*) filter (where r.status in ('PRESENT','LATE'))          as attended,
       count(*) filter (where r.status in ('PRESENT','LATE','ABSENT')) as conducted,
       count(*) filter (where r.status = 'EXCUSED')                    as excused,
       max(s.started_at)                                               as last_session_at
from attendance_records r
join attendance_sessions s using (session_id)
where s.status = 'COMPLETED'
group by s.subject_id, r.student_id;

-- Per-session roll-up for teachers/admins only (students are filtered out so they never see class-wide numbers).
create view v_session_summary with (security_invoker = true) as
select s.session_id, s.subject_id, s.teacher_id, s.method, s.status, s.started_at,
       count(r.record_id) filter (where r.status = 'PRESENT') as present,
       count(r.record_id) filter (where r.status = 'LATE')    as late,
       count(r.record_id) filter (where r.status = 'ABSENT')  as absent,
       count(r.record_id) filter (where r.status = 'EXCUSED') as excused,
       count(r.record_id) filter (where r.status in ('PRESENT','LATE','ABSENT')) as conducted
from attendance_sessions s
left join attendance_records r using (session_id)
where private.owns_session(s.session_id) or private.is_admin()
group by s.session_id;

-- Teacher changes the target of their own subject (audited).
create function set_subject_target(p_subject_id bigint, p_target numeric) returns void
language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); v_owner bigint; v_old numeric;
begin
  select teacher_id, target_percent into v_owner, v_old from subjects where subject_id = p_subject_id;
  if not found then raise exception 'subject not found' using errcode = 'PT404'; end if;
  if v_owner <> v_tid then raise exception 'not your subject' using errcode = 'PT403'; end if;
  if p_target is null or p_target < 1 or p_target > 100 then raise exception 'target must be between 1 and 100' using errcode = 'PT422'; end if;
  update subjects set target_percent = p_target where subject_id = p_subject_id;
  perform private.audit('subject.target_changed', 'subject', p_subject_id::text, jsonb_build_object('from', v_old, 'to', p_target));
end $$;

-- System-wide KPIs for the admin dashboard (admin only). "Today" is evaluated in the caller's timezone.
create function admin_overview(p_tz text default 'UTC') returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
declare v_tz text := p_tz; v_attended bigint; v_conducted bigint;
begin
  perform private.require_admin();
  if not exists (select 1 from pg_timezone_names where name = v_tz) then v_tz := 'UTC'; end if;
  select count(*) filter (where r.status in ('PRESENT','LATE')), count(*) filter (where r.status in ('PRESENT','LATE','ABSENT'))
    into v_attended, v_conducted
  from attendance_records r join attendance_sessions s using (session_id) where s.status = 'COMPLETED';
  return jsonb_build_object(
    'teachers',          (select count(*) from teachers where is_active),
    'pending_teachers',  (select count(*) from teachers where not is_active),
    'students',          (select count(*) from students where is_active),
    'subjects',          (select count(*) from subjects),
    'sessions_today',    (select count(*) from attendance_sessions where (started_at at time zone v_tz)::date = (now() at time zone v_tz)::date and status <> 'CANCELLED'),
    'attended',          v_attended,
    'conducted',         v_conducted,
    'average_attendance', case when v_conducted > 0 then round(100.0 * v_attended / v_conducted, 1) else null end);
end $$;

grant select on v_subject_student_attendance, v_session_summary to authenticated;
revoke all on v_subject_student_attendance, v_session_summary from anon;
grant select on v_subject_student_attendance, v_session_summary to service_role;
revoke execute on function set_subject_target(bigint, numeric), admin_overview(text) from public, anon;
grant execute on function set_subject_target(bigint, numeric), admin_overview(text) to authenticated, service_role;
