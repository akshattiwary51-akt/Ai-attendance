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

For local development, copy `.env.example` → `.env`; the app loads that file from the project root, without overriding variables already set in the process. For deployment, configure secrets in Streamlit or the hosting provider rather than relying on a local `.env` file. Fill in the Supabase credentials in either configuration.
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
