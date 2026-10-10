-- Phase 9: per-session recognition statistics (counts only, no biometric data) so repeated recognition failures can be flagged.
alter table attendance_sessions add column if not exists recognition_stats jsonb
  check (recognition_stats is null or (jsonb_typeof(recognition_stats) = 'object' and pg_column_size(recognition_stats) < 2000));

create or replace function set_session_recognition_stats(p_session_id bigint, p_stats jsonb)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_tid bigint := private.require_teacher(); s attendance_sessions%rowtype; k text; v jsonb;
begin
  select * into s from attendance_sessions where session_id = p_session_id for update;
  if not found then raise exception 'session not found' using errcode = 'PT404'; end if;
  if s.teacher_id <> v_tid then raise exception 'not your session' using errcode = 'PT403'; end if;
  if s.status <> 'OPEN' then raise exception 'session is not open' using errcode = 'PT409'; end if;
  if p_stats is null or jsonb_typeof(p_stats) <> 'object' then raise exception 'stats must be an object' using errcode = 'PT422'; end if;
  for k, v in select * from jsonb_each(p_stats) loop           -- whitelist: numeric counters only
    if k not in ('faces','recognized','unknown','ambiguous','low_quality','too_small','segments') or jsonb_typeof(v) <> 'number' or (v #>> '{}')::numeric < 0 then
      raise exception 'invalid stats key or value: %', k using errcode = 'PT422';
    end if;
  end loop;
  update attendance_sessions set recognition_stats = p_stats where session_id = p_session_id;
end $$;

revoke execute on function set_session_recognition_stats(bigint, jsonb) from public, anon;
grant  execute on function set_session_recognition_stats(bigint, jsonb) to authenticated, service_role;
