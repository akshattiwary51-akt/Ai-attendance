# SnapClass — Phase 1 Audit

Source code is the specification (the original README was one line). All 19 Python files / ~1,400 lines were read.
Status: **FIXED** = changed + covered by a test · **OPEN** = planned in the phase shown · **UNVERIFIED** = could not be confirmed from the repo.

## Original architecture
`app.py` → `screens/{home,teacher,student}` → `components/dialog_*` → `database/db.py` (supabase-py, module-level client built from `st.secrets`) and `pipelines/{face,voice}`.
UI code queried Supabase directly (`teacher_screen`, 3 dialogs) and held business logic inside button handlers.
Tables inferred from queries: `teachers`, `students` (`face_embedding`, `voice_embedding`), `subjects`, `subject_students`, `attendance_logs` (`student_id, subject_id, timestamp, is_present`).

## Bugs
| # | Finding | Status |
|---|---|---|
| B1 | **Only one subject shown** — `stats`, `share_btn`, `subject_card()` were dedented out of the `for` loop (reproduced: 1 of 3 rendered). Share closure also late-bound `sub`. | FIXED (`test_all_subjects_render…`) |
| B2 | Attendance silently truncated at 1000 rows (PostgREST max-rows) → wrong percentages/records | FIXED (`fetch_all` paging, tested) |
| B3 | Confirming twice / rerun inserted duplicate attendance; "session" = identical timestamp string | **FIXED (Phase 2):** explicit `attendance_sessions` + `unique(session_id, student_id)`; confirm is atomic and idempotent (DB-tested) |
| B4 | Face match: SVM always predicts *some* student, then distance checked against only the **first** stored vector; model trained on ALL students not the class; global `cache_resource` went stale across users | FIXED: nearest-gallery matching vs enrolled roster only, UNKNOWN beyond threshold |
| B5 | `get_trained_model` returned `None`/`0`/dict inconsistently; `except ValueError: pass` hid training failure | FIXED (SVM removed) |
| B6 | Voice dialog crashed on `audio_data.read()` when nothing recorded; `Source` column mixed float and `"-"`; stale results from another subject appeared | FIXED |
| B7 | `except Exception: pass/st.error('Sync failed!')`, `st.error` inside pipelines, generic "Unexpected Error!" | FIXED (typed errors, safe messages, logs) |
| B8 | Logout left photos, `user_role`, results in session → leaked to next user | FIXED (`test_logout_clears_all_user_state`) |
| B9 | Importing any module needed live Supabase secrets; heavy libs imported at module top | FIXED (lazy client/models) |
| B10 | `bcrypt>=5` raises on passwords >72 bytes → login/register 500 | FIXED |
| B11 | Enroll dialog: no feedback for unknown code; no trimming; ambiguous duplicate codes picked `data[0]` | FIXED |
| B12 | Typos / malformed HTML: `tihs`, `Sucessfully`, `Prcessing`, `items-align`, `<h2>…</h1>`, `'N'A'`, `pop('subject_student')`; QR link lacked `https://` | FIXED |
| B13 | Naive `datetime.now()` timestamps | FIXED for new rows (UTC-aware). Legacy naive rows read as UTC |

## Security
| # | Finding | Status |
|---|---|---|
| S1 | No schema/RLS in the original repo: with an anon key and RLS off, anyone could read all biometrics/password hashes. | **MITIGATED (Phase 2):** RLS enabled on every table with no policies; anon/authenticated revoked (DB-tested); app must use the *service-role* key server-side. Per-user policies: Phase 3 |
| S2 | **Stored XSS:** teacher-controlled subject name rendered with `unsafe_allow_html` to students | FIXED (escaped, tested) |
| S3 | Session state held full `students`/`teachers` rows incl. **password hash and biometric embeddings** | FIXED (id/name only) |
| S4 | Face-only login with no liveness: a printed photo logs in as that student. | **FIXED (Phase 3):** face is no longer a credential (email + password via Supabase Auth). Face may return as a *second factor* after liveness (Phase 6) |
| S5 | Any unrecognised face can create an account (no roll no./email/consent) | PARTIAL (Phase 3): registration needs email + password, a single clear face and an explicit biometric-consent tick; teachers need admin approval. Multi-sample onboarding + image-quality gating: Phase 8 |
| S6 | Authorization trusts Streamlit session state only | **FIXED (Phase 3):** the database acts on the caller's JWT (`auth.uid()`); RLS on every table; mutations via definer functions that take no caller-supplied identity. Verified with a mutation-tested policy matrix (anon/student/teacher/admin/inactive) and over real HTTP/JWT |
| S7 | No password policy / unlimited login attempts | FIXED: ≥8 chars enforced; credentials, throttling and email confirmation now handled by Supabase Auth (enable *Confirm email* + its rate limits in the dashboard) |
| S8 | Uploads had no size/type validation (decompression bombs) | FIXED (size cap, verified decode, downscale) |
| S9 | Permanent guessable subject code = enrollment | OPEN Phase 11 (signed expiring invites) |
| S10 | No `.gitignore` (risk of committing `secrets.toml`) | FIXED |

## Design / scalability
- No schema/migrations in repo → Phase 2. `get_all_students()` per login pulled every embedding → FIXED (single-student fetch; gallery fetched once per run, not per image).
- Hard-coded deployment domain and third-party image URLs (ibb.co) → domain now `APP_BASE_URL`; images OPEN (Phase 4).
- Light-theme-only cards (hard-coded white) → OPEN Phase 4.
- Unpinned dependencies; `scikit-learn` no longer needed → removed; versions pinned as far as verified, full pin Phase 12.
- Zero tests originally → 57 now.

## Phase 2 summary (database + sessions)
Clean-install schema in `supabase/migrations/0001_init.sql` (no legacy data was migrated; the user had none): `teachers, students, face_profiles, voice_profiles, subjects, enrollments, attendance_sessions, attendance_records, attendance_corrections, audit_logs`, with FKs, unique constraints (enrollment, record per student/session, subject code, username, roll no., email, one OPEN session per subject), `timestamptz`, `created_at/updated_at`, creator columns, and an append-only audit log.
Session lifecycle: `OPEN → COMPLETED | CANCELLED`, reopen, audited corrections with undo. Statuses PRESENT/LATE/ABSENT/EXCUSED/UNKNOWN/REJECTED; "manually corrected" is a flag (so the real present/absent meaning is never lost). EXCUSED is neutral in percentages; PRESENT+LATE count as attended.
**Not in Phase 2:** `users/profiles/notifications` tables (Phase 3 / 11), multiple-sample student onboarding UI (Phase 8: schema already supports many face samples; the app still enrols one), admin role (Phase 3/4).

## Phase 3 summary (authentication, authorization, RLS)
Migration `0002_auth_rls.sql`: `profiles` (user → exactly one of ADMIN / TEACHER / STUDENT, linked to a teacher or student row, `is_active`), `private.*` SECURITY DEFINER helpers (avoid recursive policies), RLS policies on all 11 tables, identity-derived functions (`create/complete/cancel/reopen_attendance_session`, `correct_attendance_record`, `undo_attendance_correction`, `enroll_by_code`, `preview_subject`, `admin_set_active`) and the service-role-only `provision_account`.
App: `Principal` + per-user PostgREST client (`get_client()` never falls back to the service key), token refresh, forced logout on expiry, teacher approval workflow, admin console (approvals, activate/deactivate, audit log), email/password login for all portals, consent notice on student registration, `scripts/create_admin.py`.
Deliberate behaviour changes: face-only student login removed (see S4); teachers now register with email and wait for approval (configurable); admins cannot read biometric templates; students cannot read their own templates (they never need to).

## Known limitations after Phase 3
- **Subject codes are guessable credentials for joining a class** (`enroll_by_code` / `preview_subject` accept any code, rate-limited only by Supabase). Replaced by signed, expiring invites in Phase 11.
- Registration is open: anyone can create student accounts (spam/abuse). Mitigate with Supabase CAPTCHA/rate limits; roster-based pre-registration can come with Phase 8.
- Biometric deletion/consent withdrawal has a notice but no self-service button yet (Phase 12).
- Student profile edit, password reset UI (use Supabase's email flow) and admin "reset enrollment" are not built.
- Per-user DB client + JWT travel through Streamlit server memory (`st.session_state`), never to the browser.

## What is still unchanged
dlib/Resemblyzer models, UI design/dashboards. Phases 4–8.

## Not verified in this environment
No Supabase project, dlib, `face_recognition_models`, librosa or Resemblyzer were available. Those paths are covered by unit tests of the pure logic and mocked services, **not** exercised end-to-end. Run the app against your Supabase project and a few real photos before relying on it.

## Phase 4 notes
Home-page text was unreadable in dark mode (fixed text colour on a fixed light panel); student percentages were computed client-side from raw rows (now from DB views); admin metrics came from list lengths (now `admin_overview`). Known limitation: dashboards read all rows for the caller's subjects (fine for classroom scale; paginate/aggregate in SQL for very large deployments).

## Phase 5 notes
Observed on the same test photo: the dlib HOG detector reported a second "face" (a false positive); the SCRFD detector reported exactly one. Previously a single global `FACE_THRESHOLD` (Euclidean) was applied regardless of model, and the nearest student was accepted if within it even when a different student was nearly as close; now the margin rule marks such cases AMBIGUOUS instead of guessing. Gallery loading no longer mixes models.

## Phase 6 notes
Thresholds (blur 40, brightness 60-200, min side 80 px) were calibrated on one sample photograph, not on your cameras: tune with real captures (see the Phase 12 evaluation utility). Liveness is a deterrent, not anti-spoofing certification.

## Phase 7 notes
Voice previously kept one template per student, matched every segment greedily to the nearest student (no margin, no quality check) and could mark the wrong student for any similar voice. Now: multi-sample, margin, quality gates. Not solved: replay attacks.

## Phase 8 notes
Before, a session was either face or voice with no way to combine them and no cross-check. Fusion cannot link a voice segment to a specific face in the photo (no speaker-to-face association), so it fuses per student, not per person-in-the-room.
