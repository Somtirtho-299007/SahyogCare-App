# SahyogCare API (backend)

FastAPI + SQLAlchemy. Locally it uses a SQLite file, so you don't need to install a database. In production it uses PostgreSQL.

The plan behind this code is in [`../docs/WORKFLOW.md`](../docs/WORKFLOW.md); endpoints are in [`../docs/API_SPEC.md`](../docs/API_SPEC.md).

## Status

**Step 1 of 6 (foundation) is done:**
- All database tables (`app/models.py`)
- All business rules in one file (`app/rules.py`): referral state machine, who may move a referral, vital-sign ranges, watchdog timings, rejection reasons, referral codes
- Standard error shape for every error
- Starting data: 4 facilities in Nadia and 4 fake test users (`app/seed.py`)
- Endpoints: `GET /api/v1/health`, `GET /api/v1/facilities`, `GET /api/v1/facilities/{id}`
- 15 automated tests

Facility endpoints are public for now; step 2 (login and roles) protects them.

## Run it on Windows

Needs **Python 3.11 or newer** (`python --version`).

Open a terminal in the `backend` folder:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.seed
uvicorn app.main:app --reload
```

On macOS/Linux, activate with `source .venv/bin/activate` instead.

Then open:
- http://127.0.0.1:8000/api/v1/health → `{"status": "ok", ...}`
- http://127.0.0.1:8000/docs → interactive list of every endpoint, where you can try them

Run the tests:

```bash
python -m pytest
```

Each test run uses its own throwaway database, so tests never touch your `sahyogcare.db`.

## Settings

Copy `.env.example` to `.env` to change settings. Never commit `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `SAHYOG_DATABASE_URL` | `sqlite:///./sahyogcare.db` | Database address |
| `SAHYOG_CORS_ORIGINS` | `http://localhost:5173,...` | Frontend addresses allowed to call the API |
| `SAHYOG_ENVIRONMENT` | `development` | `production` refuses to start with the default secret |
| `SAHYOG_SECRET_KEY` | `dev-only-change-me` | Signing key (tokens, referral passes) — set a long random value in production |

## Deploy on Render

Create a **Web Service** from this repo with:
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: `SAHYOG_DATABASE_URL` (the Internal Database URL of a Render PostgreSQL database), `SAHYOG_ENVIRONMENT=production`, `SAHYOG_SECRET_KEY`, `SAHYOG_CORS_ORIGINS=https://sahyogcare-app.onrender.com`

Check Render's current free-tier limits for PostgreSQL before relying on it.

## Placeholder values

Vital ranges, the SpO₂ suggestion threshold and watchdog timings in `app/rules.py` were chosen by the team, not clinicians. They must be reviewed by a doctor or public-health professional before any real use. Use only fake data.

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
    routers/       endpoints
  tests/
```
