# SahyogCare API (backend)

FastAPI + SQLAlchemy. Locally it uses a SQLite file, so you don't need to install a database. In production it uses PostgreSQL.

The plan behind this code is in [`../docs/WORKFLOW.md`](../docs/WORKFLOW.md); endpoints are in [`../docs/API_SPEC.md`](../docs/API_SPEC.md).

## Status

The backend is complete and the frontend (`../src`) uses it. To run both together, see the main [README](../README.md#run-locally).

**Beds, re-routing and ambulance (new):**
- Each hospital has wards (General, Emergency, Maternity, Paediatric, ICU) with total, occupied, held and free beds; staff update their own hospital, the coordinator any hospital in the district (`PUT /facilities/{id}/beds/{ward}`)
- Creating a referral **holds a bed** in the right ward (1 h Emergency, 6 h Priority, 48 h Routine until accepted; then until the patient is due to arrive). Arrival turns it into an occupied bed; rejection or re-routing releases it; the watchdog releases unused holds and suggests another hospital
- A full ward refuses the referral with `NO_BEDS_AVAILABLE` and the 3 best alternatives; `allow_without_bed: true` sends it anyway. A "no beds" rejection marks the ward full
- `GET /facilities/recommend?service=&latitude=&longitude=`: hospitals ranked by free beds, data freshness, recent rejections, speed of acceptance and distance, each with plain-language reasons
- `GET /referrals/{id}/alternatives` and `POST /referrals/{id}/reroute`: one-tap re-routing with a new code, full history kept, old hospital told; the patient's old code still finds the new referral
- Ambulance: ASHA requests (`POST /referrals/{id}/ambulance`), hospital dispatches with ETA (also accepts), picked up, completed on arrival; no hospital ambulance or a late one points everyone to 108
- Coordinator acts for the district health office: adds hospitals (`POST /facilities`), edits them (`PATCH /facilities/{id}`), corrects bed counts
- `python -m app.demo` plays the whole story on a throwaway database

**Watchdog, follow-ups and dashboards:**
- Watchdog runs every 5 minutes: alerts the ASHA when a referral is not accepted or the patient has not arrived in time, alerts the coordinator at twice the limit, and marks follow-ups overdue (`POST /watchdog/run` runs it now)
- Follow-ups: `/follow-ups` list, `complete` (closes the referral, late visits count), `miss`; coordinator `POST /referrals/{id}/escalate`
- `GET /dashboard/summary`: the same counts for every role from one definition of "open"; coordinators also see which facilities are slow to accept or reject most
- `GET /me/activity-summary?month=YYYY-MM`: the ASHA's monthly record of work

**Offline sync:**
- `POST /sync/batch`: upload actions queued while offline; each runs through the normal rules, retries never duplicate, conflicts come back as `SYNC_CONFLICT`
- `GET /sync/changes?since=`: what changed since the last sync

94 automated tests.

**Core workflow:**
- Patients (`/patients`) with consent check and duplicate warning; encounters with vitals checks, medicines and a triage hint
- Referrals: create (with `Idempotency-Key`), queue (most urgent first), detail with full history
- Status changes: `accept`, `reject` (fixed reasons), `arrival`, `consultation`, `outcome`, `close` — only the right role, only in the right order
- Every change is recorded as an event and the ASHA gets a notification (`/notifications`)
- Learning from rejections: "service unavailable" or "no doctor" marks that service unavailable, and search ranks that facility last; accepting marks it available
- Signed QR referral pass (`/referrals/{id}/pass`) and scanning at the desk (`/referral-passes/verify`), including offline scans synced later
- Public patient lookup with code + last 4 phone digits, rate-limited (`/public/referral-status`)
- Everyone only sees their own records: ASHA her referrals, facility staff their facility, coordinator their district

**Login and roles:**
- Login with a one-time code sent by email: `POST /api/v1/auth/otp/request`, `POST /api/v1/auth/otp/verify`
- Codes are hashed, expire after 5 minutes, lock after 5 wrong tries, and can be re-sent after 60 seconds
- Unknown emails get the same answer as registered ones, so the API never reveals who has an account
- Access token (15 minutes) and refresh token (7 days): `POST /api/v1/auth/refresh`; current user: `GET /api/v1/me`
- Role checks (`require_roles(...)`) ready for step 3; facility search now needs login
- Opening `http://127.0.0.1:8000/` goes straight to `/docs`


**Foundation:**
- All database tables (`app/models.py`)
- All business rules in one file (`app/rules.py`): referral state machine, who may move a referral, vital-sign ranges, watchdog timings, rejection reasons, referral codes
- Standard error shape for every error
- Starting data: 4 facilities in Nadia with bed counts and approximate locations, and fake test users including staff and a doctor for every hospital (`app/seed.py`)
- Endpoints: `GET /api/v1/health`, `GET /api/v1/facilities`, `GET /api/v1/facilities/{id}`

## Run it on Windows

Needs **Python 3.11 or newer** (`python --version`).

On Windows, always install with `python -m pip install ...` rather than `pip install ...`. If more than one Python is installed, plain `pip` may install into a different Python than the one `python` runs.

Open a terminal in the `backend` folder:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python -m app.seed
python -m uvicorn app.main:app --reload
```

On macOS/Linux, activate with `source .venv/bin/activate` instead.

Then open:
- http://127.0.0.1:8000/api/v1/health → `{"status": "ok", ...}`
- http://127.0.0.1:8000/docs → interactive list of every endpoint, where you can try them

## Log in from the /docs page

The test accounts are `asha@`, `staff@`, `doctor@` and `coordinator@sahyogcare.test`.

1. Open `POST /api/v1/auth/otp/request` → **Try it out** → body `{"email": "asha@sahyogcare.test"}` → **Execute**.
   In development the response contains `dev_code`, and the code is also printed in the server terminal.
2. Open `POST /api/v1/auth/otp/verify` → body `{"email": "asha@sahyogcare.test", "code": "<the code>"}` → **Execute**.
3. Copy `access_token` from the response, click **Authorize** (top right), paste it, and click **Authorize**.
4. Now protected endpoints such as `GET /api/v1/facilities` and `GET /api/v1/me` work. The token lasts 15 minutes.

## Try the whole journey from /docs

Log in as each role in turn (see above) and use **Authorize** with that role's token:

1. **ASHA** (`asha@`): `POST /patients` → `POST /patients/{id}/encounters` → `GET /facilities` (copy a facility `id`) → `POST /referrals`. Note the referral `id` and `code`.
2. **Staff** (`staff@`, Kalyani District Hospital): `GET /referrals?open=true` → `POST /referrals/{id}/accept` → `POST /referrals/{id}/arrival`.
3. **Doctor** (`doctor@`): `POST /referrals/{id}/consultation` → `POST /referrals/{id}/outcome`.
4. **ASHA** again: `GET /notifications` shows each step; `POST /referrals/{id}/close`.
5. **No login:** `POST /public/referral-status` with the code and the last 4 digits of the patient's phone.
6. **Coordinator** (`coordinator@`): `GET /dashboard/summary` shows district totals and which facility is slowest; `POST /watchdog/run` checks for silent referrals.

The test users' facility is Kalyani District Hospital, so refer to it in step 1.

## Areas (Nadia, Naihati)

Each area is a separate world. An area's coordinator sees and approves only the
people, hospitals, referrals, invite codes and beds of that area; ASHAs refer only
to hospitals in their own area. People choose their area when they sign up.

- `SAHYOG_DISTRICTS=Nadia,Naihati`: the areas this deployment serves
- `SAHYOG_COORDINATOR_EMAILS=you@gmail.com:Nadia,officer@gmail.com:Naihati`: first coordinator of each area
- `SAHYOG_OFFICE_PASSPHRASES=Naihati:<phrase>,Nadia:<phrase>`: a fixed passphrase per area that only its district office knows; entering it makes that person the area's coordinator at once (5 tries per 10 minutes)
- `SAHYOG_DEMO_DATA=false` on the live server: hides demo hospitals and switches off the `@sahyogcare.test` accounts

## Who can log in

Anyone with a real email. The first login creates the account; the person then
asks for a role (ASHA, hospital staff with their hospital, doctor, coordinator)
and every coordinator of the district sees the request in the app and approves
or rejects it in one tap. Until approved, the account sees no records.

- `SAHYOG_COORDINATOR_EMAILS`: the first coordinator(s), comma-separated
- `SAHYOG_AUTO_APPROVE_ASHA=true`: ASHAs are approved without waiting (they only ever see their own patients); other roles always need approval
- Codes are emailed through Brevo (`SAHYOG_BREVO_API_KEY`) or SMTP; at most 10 code requests per minute per IP address

## Database changes (migrations)

The server upgrades the database by itself on every start (`app/migrate.py`), so a
deploy keeps existing data. When a change adds or alters a table in `app/models.py`,
also add a migration and commit it with the change:

```bash
python -m alembic revision --autogenerate -m "short description"
```

Check the new file in `migrations/versions/` before committing. `tests/test_migrations.py`
fails if the models and migrations ever disagree.

## Tests

Run the tests:

```bash
python -m pytest
```

Each test run uses its own throwaway database, so tests never touch your `sahyogcare.db`.

See the re-routing story end to end (throwaway database, nothing saved):

```bash
python -m app.demo
```

**After pulling these changes, delete your local `sahyogcare.db` once and run `python -m app.seed` again**: the database has new tables and columns, and the app only creates missing tables, not missing columns.

## Settings

Copy `.env.example` to `.env` to change settings. Never commit `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `SAHYOG_DATABASE_URL` | `sqlite:///./sahyogcare.db` | Database address |
| `SAHYOG_CORS_ORIGINS` | `http://localhost:5173,...` | Frontend addresses allowed to call the API |
| `SAHYOG_ENVIRONMENT` | `development` | `production` refuses to start with the default secret |
| `SAHYOG_SECRET_KEY` | `dev-only-secret-change-me-before-production` | Signing key for tokens, login codes and referral passes — at least 32 random characters in production |
| `SAHYOG_SMTP_HOST` etc. | empty | Email server for login codes; empty means codes are printed in the terminal (development only) |
| `SAHYOG_WATCHDOG_ENABLED` | `true` | Background check for silent referrals and overdue follow-ups every 5 minutes |

## Deploy on Render

Create a **Web Service** from this repo with:
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: `SAHYOG_DATABASE_URL` (the Internal Database URL of a Render PostgreSQL database), `SAHYOG_ENVIRONMENT=production`, `SAHYOG_SECRET_KEY`, `SAHYOG_CORS_ORIGINS=https://sahyogcare-app.onrender.com`, and the `SAHYOG_SMTP_*` settings (production never shows `dev_code`, so login needs real email)

Check Render's current free-tier limits for PostgreSQL before relying on it.

## Placeholder values

Vital ranges, the SpO₂ suggestion threshold, watchdog timings, bed-hold times, recommendation weights and ambulance alert times in `app/rules.py` were chosen by the team, not clinicians. They must be reviewed by a doctor or public-health professional before any real use. Use only fake data.

## Folder layout

```text
backend/
  app/
    main.py        app setup, routers, CORS
    config.py      settings from environment
    db.py          database connection
    models.py      tables
    rules.py       business rules (state machine, ranges, timings)
    errors.py      standard error shape
    schemas.py     response shapes
    seed.py        starting data
    security.py    login codes, tokens, role checks
    emailer.py     sending login codes
    access.py      who may see which records
    workflow.py    status changes, events, notifications
    passes.py      signed QR referral passes
    ratelimit.py   limit for public lookups
    watchdog.py    alerts for silent referrals, overdue follow-ups, expired bed holds, ambulances
    beds.py        free beds, holding and releasing beds
    recommend.py   ranking hospitals for a patient
    ambulance.py   ambulance trips
    demo.py        re-routing story on a throwaway database
    routers/       endpoints
  tests/
```
