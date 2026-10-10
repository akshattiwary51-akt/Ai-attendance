# SnapClass — AI Attendance System

Streamlit app for AI attendance (face + voice) backed by Supabase.

## Status
Phases 1–3 of a 12-phase upgrade are complete: audit + bug fixes + layered refactor; relational schema with attendance sessions and audited corrections; Supabase Auth with ADMIN / TEACHER / STUDENT roles enforced by PostgreSQL Row Level Security. See [docs/AUDIT.md](docs/AUDIT.md) for findings and what remains.

## Layout
```
app.py                     entry point
src/screens, components    Streamlit UI only
src/services               business logic (auth, subjects, enrollment, attendance, recognition)
src/repositories           all Supabase queries + DB-function calls (paging, typed errors)
supabase/migrations        schema, constraints, audited DB functions, RLS lock-down
src/pipelines              dlib / Resemblyzer + pure matching logic
src/config, security, utils settings, bcrypt, errors, logging, image loading
tests/                     pytest (pure logic, services, repositories, AppTest UI tests)
```

## Setup
Python **3.12+**. `pip install -r requirements.txt` (dev: `requirements-dev.txt`).
**Supabase setup**
1. Create a Supabase project. *Authentication → Providers → Email*: keep email sign-in on; **turn "Confirm email" on** for production.
2. *SQL Editor*: run `supabase/migrations/0001_init.sql`, then `0002_auth_rls.sql` (in order).
3. Copy the project URL, the **anon** key and the **service_role** key into your secrets (see below).
4. Create the first administrator: `python scripts/create_admin.py you@college.edu` (needs the three env vars; prompts for a password).
5. Teachers register in the app and are **inactive until an admin approves them** (admin console → *Pending approvals*). Students register with email + password, a face photo and a consent tick.

Copy `.env.example` → `.env` or `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` and fill in Supabase credentials. The app loads `.env` automatically when started with `streamlit run app.py`.
Run: `streamlit run app.py` · Test: `pytest` (see [docs/TESTING.md](docs/TESTING.md) for the database-backed suites)

## Teacher workflow (Phase 2)
Take Attendance → pick subject → run face/voice analysis (opens an attendance **session**; a subject can have only one open session) → review → **Confirm & Save** (atomic, idempotent) or **Discard**.
Attendance Records → open a session → correct a record with a mandatory reason (audited), undo the latest correction, or reopen a completed session.

## Security model (Phase 3)
- Credentials live in **Supabase Auth**; the app has no password hashes of its own.
- After login every database call carries **the user's own JWT**, so PostgreSQL RLS decides what they can see: students see only their own enrolments/attendance; teachers only their own subjects, sessions and enrolled students; admins see accounts and the audit log but **not biometric templates**; the anon key sees nothing.
- All writes to attendance go through `SECURITY DEFINER` functions that read the caller from `auth.uid()` (no client-supplied ids) and write the audit log in the same transaction.
- The **service-role key is used only** to provision accounts and bootstrap the first admin. It never serves user queries.
- Face recognition is for *attendance only*. Face is no longer a login credential: a printed photo could impersonate any student until liveness checks exist (Phase 6).

## Phase 4 - Dashboards

- **Student**: overall %, classes missed, streak, status; per-subject progress bar with target marker and plain-language guidance ("you can miss N more classes" / "attend the next N classes to get back to target"). Below-target warning.
- **Teacher**: tabs Dashboard (KPIs, students needing attention, recent sessions), Subjects (cards + per-subject students/trend/sessions), Students (search + risk filter), Take Attendance, Sessions, Settings (per-subject attendance target).
- **Admin**: KPI cards from the `admin_overview` function (teachers, students, pending approvals, subjects, sessions today, average attendance).
- Numbers come from RLS-scoped views (`v_subject_student_attendance`, `v_session_summary`, migration `0003_analytics.sql`); only COMPLETED sessions count; attended = PRESENT+LATE; EXCUSED is neutral. Risk is rule-based and explainable (not ML). Config: `ATTENDANCE_TARGET`, `RISK_BUFFER`.
- Theme: colours are CSS variables with a dark-mode variant; the home page text contrast was fixed.

## Phase 5 - Face recognition

- **Engine interface** (`src/pipelines/face_engine.py`): `FaceRecognitionEngine.detect_and_embed(image) -> [DetectedFace(box, embedding, det_score)]`. Engines: `dlib` (baseline, HOG + ResNet-128, Euclidean) and `onnx` (SCRFD `det_500m` + ArcFace-family `w600k_mbf`, cosine; numpy + PIL + onnxruntime only). Select with `FACE_ENGINE`.
- **Templates are model-tagged.** `face_profiles.model` is stored with every sample and galleries are filtered by the active engine's model id - embeddings from different models are never compared. Switching engine therefore means students need new samples (the student dashboard prompts for one; teachers are told how many enrolled students cannot be recognised).
- **Multi-sample**: up to 5 active samples per student per model (`add_face_sample`, `remove_face_samples`, `my_face_sample_counts`; audited). A student's score is their best sample (or the mean of the best `FACE_TOP_K`).
- **Match statuses**: `RECOGNIZED`, `UNKNOWN` (nobody within threshold), `AMBIGUOUS` (two *different students* within `FACE_MARGIN` - never marked, reported for manual check), `TOO_SMALL` (below `MIN_FACE_PX`). Per-photo outcomes, photos with no face and unenrolled-for-model students are summarised for the teacher before they confirm. Confidence stored on records is a normalised 0-1 score.
- **ONNX models** are not in the repo (licence/size). Download the InsightFace `buffalo_sc` pack and put `det_500m.onnx` and `w600k_mbf.onnx` in `ONNX_MODEL_DIR`. Check the licence of the pack for your use (InsightFace pretrained models are for non-commercial research unless licensed).
- **Not validated**: thresholds are the engines' conventional defaults. I could only test same-person stability on one public photo; there was no multi-person dataset available offline, so false-accept/false-reject rates for your classroom are unmeasured. Calibrate on your own consented data (the evaluation utility arrives in Phase 12).

## Phase 6 - Face quality and liveness

- **Quality gate** (`src/pipelines/face_quality.py`, numpy only): sharpness, brightness, contrast, clipping, face size, cut-off at the frame edge and detector confidence give a 0-100 score and specific user-facing reasons ("The photo is blurry..."). Enrolment photos must pass strictly; the score is stored in `face_profiles.quality_score`.
- **Classroom photos**: faces that are hopelessly blurry/dark/small (below `CLASSROOM_MIN_QUALITY` or smeared) get status `LOW_QUALITY`: they are **not** auto-marked and the teacher is told to check manually.
- **Liveness** (`src/pipelines/liveness.py`): at registration (`LIVENESS_MODE=challenge`) the student takes a second photo after a random challenge (closer / farther / higher / lower). We require one face in each photo, the same person, two different pictures, and the requested movement.
- **Honest limits**: this deters casual spoofing (a still photo or screenshot). It does NOT stop someone who moves a photo/plays a video as asked, or a 3-D mask; no trained anti-spoofing model is bundled. Head pose is not measured (engines expose no landmarks). Add a model behind `LivenessChecker` or verify enrolment in person for high-stakes use. Extra samples added later by a logged-in student are quality-gated but need no challenge (the account is password-authenticated).

## Phase 7 - Voice

- **Backend interface** (`src/pipelines/voice_pipeline.py`): `VoiceBackend.decode/embed`; Resemblyzer is the baseline (lazy import, so the app runs without it).
- **Audio quality** (`voice_quality.py`, numpy only): speech length, level, clipping and signal-to-noise ratio, with user-facing reasons. Enrolment recordings must pass; classroom segments below quality are `LOW_QUALITY` and never marked.
- **Segmentation**: energy-based voice activity detection; short gaps bridged, blips dropped, runs longer than 6 s cut into 3 s windows so speakers who talk back to back are matched separately. Segment noise is judged against the whole recording's noise floor.
- **Matching**: the same threshold + runner-up-margin policy as faces (`VOICE_THRESHOLD`, `VOICE_MARGIN`) -> RECOGNIZED / UNKNOWN / AMBIGUOUS. Ambiguous segments are not marked; the teacher is told.
- **Multiple samples**: migration `0005_voice_samples.sql` (up to 5 per student per model, quality stored, audited add/remove RPCs, students can count but never read templates). Students add samples from their dashboard.
- **Limits**: voice is a weaker signal than the face and can be replayed from a recording (no voice anti-spoofing; no spoken-phrase verification). The VAD cannot separate overlapping speakers or reject non-speech noise that is as loud as speech. Resemblyzer was not installed in the development sandbox: the algorithms are tested with a fake encoder and synthetic audio, so real-voice accuracy and thresholds (0.65 / 0.05) are unmeasured - run the Phase 12 evaluation on real recordings before relying on it.

## Phase 8 - Multimodal fusion

"Combine Face + Voice" (Take Attendance) analyses the added photos and a voice recording together (`FACE_PLUS_VOICE` session) and applies explicit rules (`src/services/fusion_service.py`):
seen + heard = strongest (noisy-OR of the face score and the weighted voice score); seen only = present (a student need not speak); heard only = present but flagged (or accepted/rejected via `FUSION_VOICE_ONLY`); a doubtful face whose nearest student is the one the voice recognised is resolved by the voice and flagged; no evidence = absent. Weak single-modality matches are flagged `⚠ check`. The review table shows source, confidence and the reason for each student; nothing is saved until the teacher confirms, and records can be corrected afterwards (audited).
**Honest note**: the rules and weights are hand-set, not learned or calibrated - there is no labelled data. The combined number ranks evidence for the teacher; it is not a probability. Tune `FUSION_*` with the Phase 12 evaluation on your own recordings.

## Phase 9 - Analytics, prediction, anomaly detection

- **Charts** (Streamlit's built-in Altair, no new dependency): attendance trend (daily / weekly / monthly, in the display timezone), present vs late vs absent vs excused, distribution, subject comparison with target markers, class heatmap (student x class), time-slot heatmap, ranking. Teacher "Analytics" tab; students get a personal weekly trend, subject comparison and forecast.
- **Forecast** (`src/analytics/forecast.py`): interpretable Bayesian estimate - recency-weighted history updates a Beta prior; the next period's classes follow a Beta-Binomial. Gives chance of finishing below target (exact against the target boundary), expected final % with an 80% interval, the fewest classes to attend to stay on target, LOW/MEDIUM/HIGH risk and plain-language reasons (below target, consecutive absences, declining trend, little history). The number of future classes comes from the subject's own schedule (assumed 4 when too few sessions exist, and said so).
- **Evidence of quality**: unit tests check the probabilities against brute force; `forecast.backtest()` evaluates calibration on any history. On synthetic i.i.d. data (150 students, 2550 forecasts) Brier 0.055 vs 0.245 for a naive baseline, with predicted bands close to observed frequencies. Synthetic data matches the model's assumptions, so **run `backtest` on your real history** before trusting the numbers.
- **Anomaly flags** (`src/analytics/anomalies.py`, rule-based, flag-only - nothing is modified): duplicate records; same student present in two different subjects at overlapping times; unusual session attendance spike/drop (median/MAD); present/absent flip-flopping; high or repeated recognition failure rates (counts stored per session by migration `0006_recognition_stats.sql`, no biometric data); unusual teacher corrections (rate, bursts, late absent->present edits, repeated edits of one student). Teachers see flags for their own subjects; admins see all (cross-teacher concurrent attendance is only visible to admins).
- Not implemented: "repeated rapid identity changes" as a recognition-level signal (identities are not stored per face), and ML-based anomaly detection (no labelled data to justify it).

## Phase 10 - Attendance assistant

Students and teachers can ask attendance questions in plain language (student dashboard, teacher "Assistant" tab).
- **Never SQL.** The assistant can only call 10 fixed, read-only, validated tools (`src/assistant/tools.py`): students - `get_my_attendance`, `can_i_miss`, `classes_needed`, `my_risk_subjects`, `my_forecast`; teachers - `students_below`, `subject_attendance`, `students_missed_last`, `todays_summary`, `at_risk_students`. They call the normal services, so Postgres RLS still decides what exists for the user.
- **Authorization**: identities come from the logged-in principal, never from the question or the model (no tool has an id parameter); each tool is role-gated; arguments are strictly validated; subjects are resolved only among the user's own; names from the database are sanitised; admins have no assistant.
- **Two modes**: `ASSISTANT_MODE=rules` (default) - a deterministic router picks the tool and a template writes the answer; no external service, works offline. `ASSISTANT_MODE=llm` - opt-in; Claude (Messages API tool use) chooses tools and phrases the answer from tool results, in a bounded loop; falls back to rules if the key/package is missing or the call fails. **Privacy**: in LLM mode the question and the user's own result data are sent to the Anthropic API.
- Ambiguous questions ("Can I miss 2 classes?") get a clarifying question, never a guess. Questions are length-limited and rate-limited per session; chat history lives only in the session and is cleared at logout.
- **Honest limits**: the LLM adapter is tested with a fake client and a faked `anthropic` module, not against the live API (no key/network in the development sandbox). The rules router understands the example question styles, not arbitrary phrasing; unknown questions get a help message.
