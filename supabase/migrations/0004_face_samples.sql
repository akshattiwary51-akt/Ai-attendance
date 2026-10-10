-- Phase 5: model-aware, multi-sample face templates.
-- Templates from different models are never comparable, so every sample carries its model id and
-- galleries are filtered by it.

create index if not exists face_profiles_student_model_idx on face_profiles (student_id, model) where is_active;

-- provision_account gains p_face_model (default keeps the old behaviour). Drop the old signature so
-- named-argument calls resolve unambiguously.
drop function if exists provision_account(uuid, text, text, text, boolean, text, jsonb, jsonb, real);
create function provision_account(p_user_id uuid, p_role text, p_name text, p_email text, p_active boolean default true,
                                  p_roll_number text default null, p_face jsonb default null, p_voice jsonb default null,
                                  p_face_quality real default null, p_face_model text default 'dlib-resnet-128')
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
    if p_face  is not null then insert into face_profiles(student_id, embedding, quality_score, model) values (v_id, p_face, p_face_quality, coalesce(p_face_model, 'dlib-resnet-128')); end if;
    if p_voice is not null then insert into voice_profiles(student_id, embedding) values (v_id, p_voice); end if;
  else raise exception 'invalid role' using errcode = 'PT422'; end if;
  perform private.audit('account.provisioned', lower(p_role), v_id::text, jsonb_build_object('active', p_active, 'has_face', p_face is not null, 'has_voice', p_voice is not null));
  return v_id;
end $$;
revoke execute on function provision_account(uuid, text, text, text, boolean, text, jsonb, jsonb, real, text) from public, anon, authenticated;
grant  execute on function provision_account(uuid, text, text, text, boolean, text, jsonb, jsonb, real, text) to service_role;

-- A student adds an extra face sample for themselves (max 5 active per model: lighting/angle variety, bounded storage).
create or replace function add_face_sample(p_embedding jsonb, p_model text, p_quality real default null)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_student bigint := private.student_id(); v_id bigint; v_n int;
begin
  if v_student is null then raise exception 'only students can add face samples' using errcode = 'PT403'; end if;
  if p_model is null or btrim(p_model) = '' or length(p_model) > 64 then raise exception 'invalid model' using errcode = 'PT422'; end if;
  if p_embedding is null or jsonb_typeof(p_embedding) <> 'array' or jsonb_array_length(p_embedding) not between 64 and 1024 then
    raise exception 'invalid embedding' using errcode = 'PT422'; end if;
  select count(*) into v_n from face_profiles where student_id = v_student and model = p_model and is_active;
  if v_n >= 5 then raise exception 'You already have 5 face samples; remove one first.' using errcode = 'PT409'; end if;
  insert into face_profiles(student_id, embedding, model, quality_score) values (v_student, p_embedding, p_model, p_quality) returning profile_id into v_id;
  perform private.audit('face.sample_added', 'student', v_student::text, jsonb_build_object('model', p_model));
  return v_id;
end $$;

create or replace function remove_face_samples(p_model text)
returns int language plpgsql security definer set search_path = public, pg_temp as $$
declare v_student bigint := private.student_id(); v_n int;
begin
  if v_student is null then raise exception 'only students can remove face samples' using errcode = 'PT403'; end if;
  update face_profiles set is_active = false where student_id = v_student and model = p_model and is_active;
  get diagnostics v_n = row_count;
  perform private.audit('face.samples_removed', 'student', v_student::text, jsonb_build_object('model', p_model, 'count', v_n));
  return v_n;
end $$;

-- Students may count their own samples (never read embeddings).
create or replace function my_face_sample_counts()
returns table(model text, samples bigint) language sql stable security definer set search_path = public, pg_temp as $$
  select model, count(*) from face_profiles where student_id = private.student_id() and is_active group by model order by model;
$$;

revoke execute on function add_face_sample(jsonb, text, real), remove_face_samples(text), my_face_sample_counts() from public, anon;
grant  execute on function add_face_sample(jsonb, text, real), remove_face_samples(text), my_face_sample_counts() to authenticated, service_role;
