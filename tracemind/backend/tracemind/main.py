"""TraceMind backend: OTLP ingestion (/v1/*) + REST API (/api/*). Run: uvicorn tracemind.main:app --port 8100"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from tracemind import ingest
from tracemind.api.routes import router as api_router
from tracemind.api.service import Service
from tracemind.security import SecurityMiddleware, check_startup_config
from tracemind.store import PostgresTelemetryRepository, default_dsn, migrate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tracemind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_startup_config()
    dsn = default_dsn()
    migrate(dsn)
    repo = PostgresTelemetryRepository(dsn, max_size=int(os.environ.get("TRACEMIND_DB_POOL_MAX", "8")))
    app.state.telemetry_repo = repo
    ingest.configure(repo)
    app.state.service = Service(repo)
    app.state.service.reap_stale_jobs()
    yield
    repo.close()


app = FastAPI(title="TraceMind", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)
app.include_router(ingest.router)
app.include_router(api_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(request: Request) -> dict[str, str]:
    """Readiness: the database answers. 503 otherwise so orchestrators stop routing traffic here."""
    try:
        request.app.state.service.one("SELECT 1 AS ok")
    except Exception as e:
        log.warning("readiness check failed: %s", e)
        raise HTTPException(503, "database unavailable") from e
    return {"status": "ready"}
