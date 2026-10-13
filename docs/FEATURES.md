# Feature notes by phase

Detailed notes, design decisions and honest limits for each phase. The README has the overview.

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
- **Not validated**: thresholds are the engines' conventional defaults. I could only test same-person stability on one public photo; there was no multi-person dataset available offline, so false-accept/false-reject rates for your classroom are unmeasured. Calibrate on your own consented data with `scripts/evaluate_models.py` (see Phase 12 below).

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
- **Limits**: voice is a weaker signal than the face and can be replayed from a recording (no voice anti-spoofing; no spoken-phrase verification). The VAD cannot separate overlapping speakers or reject non-speech noise that is as loud as speech. Resemblyzer was not installed in the development sandbox: the algorithms are tested with a fake encoder and synthetic audio, so real-voice accuracy and thresholds (0.65 / 0.05) are unmeasured - run `scripts/evaluate_models.py voice` on real recordings before relying on it.

## Phase 8 - Multimodal fusion

"Combine Face + Voice" (Take Attendance) analyses the added photos and a voice recording together (`FACE_PLUS_VOICE` session) and applies explicit rules (`src/services/fusion_service.py`):
seen + heard = strongest (noisy-OR of the face score and the weighted voice score); seen only = present (a student need not speak); heard only = present but flagged (or accepted/rejected via `FUSION_VOICE_ONLY`); a doubtful face whose nearest student is the one the voice recognised is resolved by the voice and flagged; no evidence = absent. Weak single-modality matches are flagged `⚠ check`. The review table shows source, confidence and the reason for each student; nothing is saved until the teacher confirms, and records can be corrected afterwards (audited).
**Honest note**: the rules and weights are hand-set, not learned or calibrated - there is no labelled data. The combined number ranks evidence for the teacher; it is not a probability. Tune `FUSION_*` against your own recordings (the evaluation utility measures face and voice separately, not the fused score).

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

## UI redesign
Presentation only; services, repositories, RLS, recognition and the audited database functions are unchanged.
- `src/ui/theme.py`: design tokens (light and dark) and the one stylesheet. `.streamlit/config.toml` carries the matching native theme; edit both together.
- `src/ui/shell.py`: role-aware sidebar (logo, navigation with active indicator, profile, log out) and the signed-out auth layout. `src/ui/widgets.py` holds the shared components (page header, KPI card, status badge, stepper, empty state); `src/ui/dialogs.py` is the reusable confirmation dialog.
- Take attendance is a guided flow (`src/screens/attendance_flow.py`): Subject, Capture, Analyze, Review, Save. The review is inline; Confirm and save is guarded against double submits and Discard asks first. Reopening a session and undoing a correction also ask first; correction reasons are still mandatory.
- Status is always a glyph plus a word, never colour alone. Confidence is shown only when the recognition step produced a score.
- Preview the screens without a database: `streamlit run scripts/ui_preview.py` then open `/?role=teacher|student|admin|home`. It uses invented sample data and is never imported by the app.
- Limits: AppTest cannot click inside dialogs, so confirm buttons are checked in a browser; fonts load from Google Fonts and fall back to system fonts offline.

## Phase 11 - Invites, reports, notifications
- **Enrolment invites** (migration `0007_invites.sql`, `invite_service`, `components/invite_panel.py`): a teacher creates a link and QR code per subject with an expiry (1 hour to 30 days), a use limit, an optional enrolment window and optional per-student approval. The token is random and shown once; only its SHA-256 hash is stored (hash lookup rather than HMAC signing, because revocation and use counting need server state). Redemption is one database function with a row lock, so concurrent students cannot exceed the limit. Revoking works immediately. Every create, request, approval and enrolment is audited. Students open `/?invite=TOKEN` after logging in. The existing subject-code join still works.
- **Reports** (`report_service`, Reports page): per-subject student summary, session list and attendance matrix as CSV, plus a multi-sheet Excel workbook (needs `openpyxl`). Students can export their own history; admins can export the audit log. Cells starting with `= + - @` are neutralised against spreadsheet formula injection. Exports use the same RLS-scoped data as the screens.
- **Notifications** (`notification_service`): in-app alerts derived from real data (below target, no face sample, unfinished sessions, high-risk students, pending requests and approvals, flagged patterns). Nothing is stored. **Email and push delivery are not implemented.**
- Limits: PDF reports are not provided; invite tokens cannot be recovered after creation (create a new one); the approval queue shows only name and roll number.


## Phase 12 - Hardening, health, evaluation, deployment
- **Upload limits** (`src/utils/images.py`, `recognition_service._decode_audio`): images are rejected on size and on pixel count read from the header (before decoding), audio on byte size and on decoded duration, empty audio never reaches the decoder. Limits: `MAX_UPLOAD_MB`, `MAX_IMAGE_PIXELS`, `MAX_IMAGE_SIDE`, `MAX_AUDIO_MB`, `MAX_AUDIO_SECONDS`. Uploaded files are processed in memory; the app never uses an uploaded file name.
- **System page** (admin console, `health_service`): validates configuration (names the variable, never shows values), reports whether the face/voice packages and ONNX files are present (without loading a model), and probes each expected table as the admin, naming the migration to apply when one is missing.
- **Evaluation utility** (`scripts/evaluate_models.py`, `src/evaluation/`): measures open-set identification on a folder of labelled photos or recordings using the same matcher and policy as the app. Reports FAR, FRR, misidentification, precision, recall and accuracy with 95% Wilson intervals, a threshold sweep, a threshold suggestion for a target FAR, and score distributions. It says so when FAR cannot be measured (no held-out people) or the sample is too small to resolve. Run: `python scripts/evaluate_models.py face --data DIR --holdout 3 --out face_report.md`. **No accuracy figure for the real face or voice models exists until you run this on your data.**
- **Deployment files**: `Dockerfile`, `docker-compose.yml`, `.dockerignore` (see README).

