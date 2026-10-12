"""SahyogCare API.

Run locally:  uvicorn app.main:app --reload
Docs:         http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, models  # noqa: F401  (models must be imported so tables are registered)
from app.config import settings
from app.db import Base, engine
from app.errors import install_error_handlers
from app.routers import auth, facilities, health

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Step 1 creates tables directly. Before the first production deploy with real
    # schema changes, switch to Alembic migrations.
    Base.metadata.create_all(engine)
    yield


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


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")
