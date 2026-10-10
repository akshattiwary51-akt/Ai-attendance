-- Phase 7: multiple voice samples per student (bounded), with quality and model, mirroring face samples.
drop index if exists voice_profiles_one_active_uidx;
alter table voice_profiles add column if not exists quality_score real check (quality_score between 0 and 100);
create index if not exists voice_profiles_student_model_idx on voice_profiles (student_id, model) where is_active;

create or replace function add_voice_sample(p_embedding jsonb, p_model text default 'resemblyzer', p_quality real default null)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_student bigint := private.student_id(); v_id bigint; v_n int;
begin
  if v_student is null then raise exception 'only students can add voice samples' using errcode = 'PT403'; end if;
  if p_model is null or btrim(p_model) = '' or length(p_model) > 64 then raise exception 'invalid model' using errcode = 'PT422'; end if;
  if p_embedding is null or jsonb_typeof(p_embedding) <> 'array' or jsonb_array_length(p_embedding) not between 64 and 1024 then
    raise exception 'invalid embedding' using errcode = 'PT422'; end if;
  select count(*) into v_n from voice_profiles where student_id = v_student and model = p_model and is_active;
  if v_n >= 5 then raise exception 'You already have 5 voice samples; remove them first.' using errcode = 'PT409'; end if;
  insert into voice_profiles(student_id, embedding, model, quality_score) values (v_student, p_embedding, p_model, p_quality) returning profile_id into v_id;
  perform private.audit('voice.sample_added', 'student', v_student::text, jsonb_build_object('model', p_model));
  return v_id;
end $$;

create or replace function remove_voice_samples(p_model text)
returns int language plpgsql security definer set search_path = public, pg_temp as $$
declare v_student bigint := private.student_id(); v_n int;
begin
  if v_student is null then raise exception 'only students can remove voice samples' using errcode = 'PT403'; end if;
  update voice_profiles set is_active = false where student_id = v_student and model = p_model and is_active;
  get diagnostics v_n = row_count;
  perform private.audit('voice.samples_removed', 'student', v_student::text, jsonb_build_object('model', p_model, 'count', v_n));
  return v_n;
end $$;

create or replace function my_voice_sample_counts()
returns table(model text, samples bigint) language sql stable security definer set search_path = public, pg_temp as $$
  select model, count(*) from voice_profiles where student_id = private.student_id() and is_active group by model order by model;
$$;

revoke execute on function add_voice_sample(jsonb, text, real), remove_voice_samples(text), my_voice_sample_counts() from public, anon;
grant  execute on function add_voice_sample(jsonb, text, real), remove_voice_samples(text), my_voice_sample_counts() to authenticated, service_role;
