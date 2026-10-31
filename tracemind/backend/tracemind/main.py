"""TraceMind backend: OTLP ingestion (/v1/*) + REST API (/api/*). Run: uvicorn tracemind.main:app --port 8100"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tracemind import ingest
from tracemind.api.routes import router as api_router
from tracemind.api.service import Service
from tracemind.store import PostgresTelemetryRepository, default_dsn, migrate

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = default_dsn()
    migrate(dsn)
    repo = PostgresTelemetryRepository(dsn, max_size=int(os.environ.get("TRACEMIND_DB_POOL_MAX", "8")))
    app.state.telemetry_repo = repo
    ingest.configure(repo)
    app.state.service = Service(repo)
    app.state.service.reap_stale_jobs()
    yield
    repo.close()


app = FastAPI(title="TraceMind", version="0.1.0", lifespan=lifespan)
app.include_router(ingest.router)
app.include_router(api_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
