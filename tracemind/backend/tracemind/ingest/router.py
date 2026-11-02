"""OTLP/HTTP protobuf endpoints. Mount `router` in main.py; set app.state.telemetry_repo (or call configure())."""
from __future__ import annotations

import threading
import zlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)

from tracemind.ingest.otlp import OtlpDecodeError, parse_logs, parse_traces

MAX_BODY = 32 * 1024 * 1024
router = APIRouter()
_repo: Any = None


def configure(repo: Any) -> None:
    global _repo
    _repo = repo


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.c = {"trace_requests": 0, "log_requests": 0, "spans_accepted": 0, "logs_accepted": 0,
                  "rejected_requests": 0, "storage_errors": 0}
        self.last_received_at: str | None = None
        self.last_error: str | None = None

    def add(self, **kw: int) -> None:
        with self.lock:
            for k, v in kw.items():
                self.c[k] += v
            if "spans_accepted" in kw or "logs_accepted" in kw:
                self.last_received_at = datetime.now(UTC).isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {**self.c, "last_received_at": self.last_received_at, "last_error": self.last_error}


stats = Stats()


def _repo_for(request: Request) -> Any:
    repo = getattr(request.app.state, "telemetry_repo", None) or _repo
    if repo is None:
        raise HTTPException(503, "telemetry repository not configured")
    return repo


async def _body(request: Request) -> bytes:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/x-protobuf":
        stats.add(rejected_requests=1)
        raise HTTPException(415, "Content-Type must be application/x-protobuf")
    raw = await request.body()
    enc = request.headers.get("content-encoding", "identity").strip().lower()
    if enc in ("", "identity"):
        data = raw
    elif enc == "gzip":
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            data = d.decompress(raw, MAX_BODY + 1)
            if len(data) > MAX_BODY or d.unconsumed_tail:
                raise HTTPException(413, "decompressed body too large")
        except (zlib.error, EOFError, OSError) as exc:
            stats.add(rejected_requests=1)
            raise HTTPException(400, "invalid gzip body") from exc
    else:
        stats.add(rejected_requests=1)
        raise HTTPException(415, f"unsupported Content-Encoding: {enc}")
    if len(data) > MAX_BODY:
        raise HTTPException(413, "body too large")
    return data


def _ok(resp_cls: Any) -> Response:
    return Response(content=resp_cls().SerializeToString(), media_type="application/x-protobuf")


@router.post("/v1/traces")
async def ingest_traces(request: Request) -> Response:
    repo = _repo_for(request)
    data = await _body(request)
    try:
        spans = parse_traces(data)
    except OtlpDecodeError as e:
        stats.add(rejected_requests=1)
        raise HTTPException(400, str(e)) from e
    try:
        n = await run_in_threadpool(repo.save_spans, spans)
    except Exception as e:  # storage failure: 503 so the collector retries
        stats.add(storage_errors=1)
        stats.last_error = f"{type(e).__name__}: {e}"
        raise HTTPException(503, "storage unavailable") from e
    stats.add(trace_requests=1, spans_accepted=n)
    return _ok(ExportTraceServiceResponse)


@router.post("/v1/logs")
async def ingest_logs(request: Request) -> Response:
    repo = _repo_for(request)
    data = await _body(request)
    try:
        logs = parse_logs(data)
    except OtlpDecodeError as e:
        stats.add(rejected_requests=1)
        raise HTTPException(400, str(e)) from e
    try:
        n = await run_in_threadpool(repo.save_logs, logs)
    except Exception as e:
        stats.add(storage_errors=1)
        stats.last_error = f"{type(e).__name__}: {e}"
        raise HTTPException(503, "storage unavailable") from e
    stats.add(log_requests=1, logs_accepted=n)
    return _ok(ExportLogsServiceResponse)


@router.get("/api/ingest/stats")
async def ingest_stats() -> dict[str, Any]:
    return stats.snapshot()
