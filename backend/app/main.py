import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, incidents
from app.api.auth import migrate_legacy_demo_user
from app.config import get_settings
from app.db import init_db
from app.hindsight import client as hindsight

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    migrate_legacy_demo_user()
    yield


app = FastAPI(title="Incident Response Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(incidents.router)


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    # Public connectivity check only; per-user memory stats are served by /api/auth/me.
    hs = await hindsight.health()
    return {
        "status": "ok",
        "groq": {"configured": bool(s.groq_api_key), "model": s.groq_model},
        "hindsight": {"configured": bool(s.hindsight_api_key), **hs},
    }
