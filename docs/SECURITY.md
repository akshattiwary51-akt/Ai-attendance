# Security overview

What is enforced, where, and how it is tested. Findings from the original code are in [AUDIT.md](AUDIT.md).

## Authentication
- Credentials live in Supabase Auth; the app stores no password hashes. Email + password only (face-only login was removed: a printed photo could log in).
- Teacher accounts are inactive until an admin approves them (`REQUIRE_TEACHER_APPROVAL`). Admin accounts are created out of band (`scripts/create_admin.py`).
- Session tokens refresh and expire in `app.py`; logout clears all user state (tested).
- Login throttling and email confirmation are Supabase Auth settings: enable *Confirm email* and review its rate limits.

## Authorization
- Every repository call uses a client built from the **logged-in user's JWT** (`get_client()` never falls back to the service key). PostgreSQL RLS is the real access control; the UI only hides what the database would refuse anyway.
- RLS is enabled on every table; `anon` has no table or function access. Policy helpers live in a `private` schema as `SECURITY DEFINER` functions to avoid recursive policies. Views use `security_invoker`.
- Writes to attendance, enrolment, invites and samples go through audited `SECURITY DEFINER` functions that read the caller from `auth.uid()`; none accepts a caller-supplied identity. Failures map to typed errors (PT403/404/409/422).
- Biometric templates: only a teacher of a subject the student is enrolled in can read them (needed for matching); students can count their own samples but not read them; admins cannot read them.
- The service-role key is used only to provision accounts.
- The assistant has 10 fixed read-only tools, none with an id parameter; role gates and argument validation apply, and it calls the same RLS-scoped services.

## Data handling
- Invite tokens: 192-bit random, shown once, only the SHA-256 hash is stored (the hash column is not granted to clients); expiry, use limit, row-locked redemption, revocation, audit.
- Logs never contain secrets, tokens, passwords or embeddings (`utils/logging.py` redacts by key name; recognition code logs types and counts only). `Principal.__repr__` hides the token.
- Error messages shown to users are explicit sentences only; driver errors are logged by type and never displayed.
- Reports: per-user, RLS-scoped; no embeddings; cells starting with `= + - @` are neutralised (spreadsheet formula injection).
- All user-controlled text rendered with `unsafe_allow_html` goes through `utils.html.esc` (tested, including the original stored-XSS case).
- Notifications are derived on the fly; nothing extra is stored.

## Uploads
Images: size cap, pixel-count cap read from the header, verified decode, downscale. Audio: byte cap, decoded-duration cap, empty rejected before decoding. Everything is processed in memory; uploaded file names are never used. Limits are configurable (`MAX_*`).

## Container
Non-root user, read-only root filesystem, `no-new-privileges`, secrets via environment only (`.env` is excluded from the image and git).

## Known gaps
- No anti-spoofing beyond a movement challenge; voice replay is possible.
- LLM assistant mode sends the question and the user's own results to the Anthropic API (opt-in, off by default).
- No self-service deletion of biometric data / consent withdrawal.
- No application-level login rate limiting beyond Supabase's; no WAF or CSRF layer beyond what Streamlit provides.
- Supabase Auth and the container image were not tested live.
