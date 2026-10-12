"""SahyogCare API.

Run locally:  uvicorn app.main:app --reload
Docs:         http://127.0.0.1:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, models  # noqa: F401  (models must be imported so tables are registered)
from app.accounts import ensure_coordinators
from app.config import settings
from app.db import SessionLocal
from app.errors import install_error_handlers
from app.migrate import run_migrations
from app.routers import (
    access,
    auth,
    facilities,
    followups,
    health,
    insights,
    notifications,
    patients,
    public,
    referrals,
    sync,
    users,
)
from app.watchdog import watchdog_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create or upgrade the database tables (see app/migrate.py and migrations/versions).
    run_migrations()
    with SessionLocal() as db:
        ensure_coordinators(db)
    task = asyncio.create_task(watchdog_loop(SessionLocal)) if settings.watchdog_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="SahyogCare API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

API = "/api/v1"
app.include_router(health.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(facilities.router, prefix=API)
app.include_router(patients.router, prefix=API)
app.include_router(referrals.router, prefix=API)
app.include_router(notifications.router, prefix=API)
app.include_router(followups.router, prefix=API)
app.include_router(insights.router, prefix=API)
app.include_router(sync.router, prefix=API)
app.include_router(public.router, prefix=API)
app.include_router(users.router, prefix=API)
app.include_router(access.router, prefix=API)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")
