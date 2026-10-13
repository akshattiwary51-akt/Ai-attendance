# SnapClass — AI Attendance System

A Streamlit application for classroom attendance with face and voice recognition, backed by Supabase (PostgreSQL + Auth).
Teachers run attendance sessions, review the results and save them; students see their own attendance and guidance; administrators manage accounts and watch for anomalies.

> **Read the limitations first.** Face and voice thresholds have **not** been measured on real classroom data, liveness is a deterrent and not anti-spoofing, and the Docker image, Supabase Auth, dlib, Resemblyzer and the Anthropic API were never exercised live in the development sandbox. See [Limitations](#limitations).

## Architecture

```
Browser ── Streamlit (app.py)
              │
   screens / components / ui      presentation only (no queries, no business rules)
              │
          services                business rules: auth, subjects, enrolment, sessions, attendance,
              │                   recognition, fusion, dashboards, analytics, reports, invites, health
   ┌──────────┼───────────────┐
repositories  pipelines       analytics / assistant / evaluation
(all Supabase  (face + voice   (pure functions; fixed, role-gated assistant tools)
 access)       models)
   │
PostgREST ── per-user JWT ──▶ PostgreSQL: RLS on every table, audited SECURITY DEFINER functions
```

A modular monolith: one deployable app, one database. No queue, cache or orchestration layer.

Key properties
- **Identity** is a Supabase Auth account with a role profile (ADMIN / TEACHER / STUDENT). Every database call carries the logged-in user's own JWT, so Row Level Security decides what each user can see. The service-role key is used only to create accounts.
- **Attendance sessions** go OPEN → COMPLETED or CANCELLED. Confirming is atomic and idempotent; corrections need a reason, are audited and can be undone; completed sessions can be reopened.
- **Counting rules**: attended = PRESENT + LATE; conducted = PRESENT + LATE + ABSENT; EXCUSED is neutral; only COMPLETED sessions count.

## Folder structure
```
app.py                     entry point (session handling, ?invite= / ?join-code= links)
src/screens, components    Streamlit pages and dialogs
src/ui                     theme tokens, shell/sidebar, widgets, charts, notifications
src/services               business logic
src/repositories           every Supabase query / RPC call, typed error translation
src/pipelines              face engines (dlib, ONNX), quality, liveness, voice, pure matching
src/analytics              attendance math, forecast, trends, anomaly rules (pure)
src/assistant              tools, rules router, optional LLM adapter, rate limiter
src/evaluation             offline identification metrics (used by scripts/evaluate_models.py)
src/security, config, database, utils   principal/auth provider, settings, clients, errors, logging
supabase/migrations        0001 … 0007 (schema, RLS, views, samples, stats, invites)
scripts                    create_admin.py, evaluate_models.py, test_stack.sh, ui_preview.py
tests/                     pytest (unit, AppTest UI, real PostgreSQL + PostgREST + JWT integration)
docs/                      AUDIT.md (original bugs), FEATURES.md (per-phase notes), TESTING.md, SECURITY.md
Dockerfile, docker-compose.yml
```

## Database
Seven ordered migrations in `supabase/migrations/`; run them in order in the Supabase SQL editor (or `supabase db push`).

| Migration | Adds |
|---|---|
| 0001_init | teachers, students, face/voice profiles, subjects, enrolments, attendance sessions/records/corrections, audit log, audited functions |
| 0002_auth_rls | role profiles, RLS on every table, identity-from-JWT functions |
| 0003_analytics | per-subject targets, attendance views (`security_invoker`), admin overview |
| 0004_face_samples | up to 5 model-tagged face samples per student, quality score |
| 0005_voice_samples | up to 5 voice samples per student per model |
| 0006_recognition_stats | per-session recognition counts (numbers only, no biometric data) |
| 0007_invites | expiring enrolment invites (token hash only), enrolment requests and approval |

## Features
Teacher: subjects with target %, guided take-attendance flow (face, voice, or both), review before saving, session history with audited corrections, analytics, anomaly flags, invite links and QR codes, CSV/Excel reports, assistant.
Student: own attendance by subject, "classes you can miss" / "classes to recover", forecast and risk, face and voice samples, history export, assistant.
Admin: overview, approve teachers, activate/deactivate accounts, anomalies across the system, audit log, system health page.
Details and design notes per phase: [docs/FEATURES.md](docs/FEATURES.md).

## Setup (local)
Python **3.12+**.
```bash
pip install -r requirements.txt            # dev/test: pip install -r requirements-dev.txt
cp .env.example .env                       # fill in the three Supabase values at least
streamlit run app.py
```
Windows: use `py -3.12 -m venv .venv` and `.venv\Scripts\activate`; `dlib-bin` installs a prebuilt wheel on both Windows and Linux. Resemblyzer pulls in PyTorch (large download).

**Supabase**
1. Create a project. *Authentication → Providers → Email*: keep email sign-in on and turn **Confirm email** on for production.
2. Run the seven migrations in order.
3. Copy the project URL, the **anon** key and the **service_role** key into `.env` (or `.streamlit/secrets.toml`).
4. Create the first administrator: `python scripts/create_admin.py you@college.edu` (prompts for a password).
5. Teachers register in the app and stay inactive until an admin approves them (`REQUIRE_TEACHER_APPROVAL`). Students register with email, password, a face photo and a consent tick.

## Deployment (Docker)
```bash
cp .env.example .env     # real values; .env is git-ignored and excluded from the image
docker compose up --build
# open http://localhost:8501
```
- The container runs as a non-root user with a read-only root filesystem and a health check on Streamlit's `/_stcore/health`.
- The database is your Supabase project; the container has no database of its own.
- For `FACE_ENGINE=onnx`, put the model files in `./models` (mounted read-only) — see [docs/FEATURES.md](docs/FEATURES.md#phase-5---face-recognition).
- Put a TLS-terminating reverse proxy in front for anything beyond localhost and set `APP_BASE_URL` to the public https URL (invite links are built from it).
- Streamlit Community Cloud also works: push the repo, add the same keys under *Secrets*.
- After deploying, sign in as the admin and open **System**: it checks configuration, models and that all migrations were applied.
- **The Dockerfile and compose file were written and the compose file syntax-checked, but the image was not built or run** (no container runtime was available in the development sandbox). Expect to iterate on first build.

## Environment variables
Set in the environment, `.env`, or Streamlit secrets. `.env.example` has every variable with comments.

| Variable | Default | Purpose |
|---|---|---|
| SUPABASE_URL, SUPABASE_ANON_KEY | – (required) | project URL and public key (used with each user's JWT) |
| SUPABASE_SERVICE_ROLE_KEY | – | **secret**; account provisioning and admin bootstrap only |
| REQUIRE_TEACHER_APPROVAL | true | new teachers inactive until approved |
| APP_BASE_URL, APP_TIMEZONE | example URL, UTC | invite links; display time zone (IANA name) |
| ATTENDANCE_TARGET, RISK_BUFFER | 75, 5 | default target %; points above target counted as "watch" |
| FACE_ENGINE | dlib | `dlib` or `onnx` (`ONNX_MODEL_DIR`, `ONNX_DET_MODEL`, `ONNX_REC_MODEL`) |
| FACE_THRESHOLD, FACE_MARGIN, FACE_TOP_K, MIN_FACE_PX | engine default | matching policy (unset = engine default) |
| LIVENESS_MODE | challenge | `challenge` or `off` |
| CLASSROOM_MIN_QUALITY | 35 | below this, classroom faces are flagged, not marked |
| VOICE_THRESHOLD, VOICE_MARGIN | 0.65, 0.05 | cosine similarity and runner-up gap |
| VOICE_ENROL_SECONDS, VOICE_MIN_SNR_DB, MIN_SPEECH_SECONDS | 2.0, 10, 0.5 | audio quality gates |
| FUSION_VOICE_WEIGHT, FUSION_REVIEW_BELOW, FUSION_VOICE_ONLY | 0.6, 0.6, review | face+voice rules |
| ASSISTANT_MODE | rules | `rules` or `llm` (`ASSISTANT_MODEL`, **secret** `ANTHROPIC_API_KEY`, `ASSISTANT_RATE_PER_HOUR`) |
| MAX_UPLOAD_MB, MAX_IMAGE_SIDE, MAX_IMAGE_PIXELS | 10, 2000, 40000000 | image limits |
| MAX_AUDIO_MB, MAX_AUDIO_SECONDS | 15, 600 | audio limits |
| LOG_LEVEL | INFO | logging |

## Testing
`pytest` runs the suites that need no services (unit, service, Streamlit AppTest UI). The database-backed suites run a real PostgreSQL + PostgREST with minted JWTs and are skipped unless their env vars are set:
```bash
eval "$(sh scripts/test_stack.sh | grep '^export')" && pytest -q
```
See [docs/TESTING.md](docs/TESTING.md) for what is and is not covered.

## Measuring recognition on your data
```bash
python scripts/evaluate_models.py face  --data photos/ --holdout 3 --out face_report.md
python scripts/evaluate_models.py voice --data clips/  --holdout 3 --out voice_report.md
```
One folder per person. Reports FAR, FRR, misidentification, precision, recall, accuracy with confidence intervals, a threshold sweep and a suggested threshold. Get consent before collecting biometric data.

## Security
Summary in [docs/SECURITY.md](docs/SECURITY.md): RLS everywhere, JWT-scoped access, audited definer functions, hashed invite tokens, upload bounds, HTML escaping, spreadsheet-formula guard, redacted logging, no biometric vectors in logs or exports.

## Limitations
- **Recognition accuracy is unmeasured.** Thresholds are the engines' conventional defaults. Use `scripts/evaluate_models.py` on consented, representative data before relying on automatic marking. Teachers review every result before saving.
- **No anti-spoofing.** The enrolment movement challenge deters casual photo use only; voice can be replayed from a recording.
- **Never run live in the sandbox:** dlib, Resemblyzer (voice logic tested with a fake encoder and synthetic audio), the Anthropic API (fake client), Supabase Auth/GoTrue (fake provider; the database layer is tested against real PostgreSQL + PostgREST), and the Docker image.
- Fusion weights are hand-set; forecasts were backtested only on synthetic data.
- Notifications are in-app only (no email/push). No PDF export. Invite tokens cannot be recovered after creation.
- No self-service biometric deletion or consent withdrawal yet; an admin can deactivate accounts, but template deletion is a database operation.
- The UI preview harness and browser checks used invented data; the invite, reports and notification screens were checked by automated tests but not viewed in a browser.

## Future improvements
Trained anti-spoofing model; self-service biometric deletion; email notifications; PDF reports; evaluation of the fused face+voice score; load testing and a rate limit on login attempts beyond Supabase's; pinned lock file.
