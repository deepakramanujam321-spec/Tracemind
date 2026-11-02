import gzip

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)
from otlp_fixtures import TRACE, log_request, synthetic_redelivery

from tracemind.ingest import router
from tracemind.ingest.router import stats

PB = {"content-type": "application/x-protobuf"}


@pytest.fixture()
def client(repo):
    app = FastAPI()
    app.state.telemetry_repo = repo
    app.include_router(router)
    stats.reset()
    return TestClient(app)


def test_post_traces_then_read_back_through_repository(client, repo):
    r = client.post("/v1/traces", content=synthetic_redelivery().SerializeToString(), headers=PB)
    assert r.status_code == 200
    ExportTraceServiceResponse().ParseFromString(r.content)
    spans = repo.get_trace(TRACE)
    assert len(spans) == 6
    assert {s.service_name for s in spans} == {"demo-api", "demo-worker"}
    s = client.get("/api/ingest/stats").json()
    assert s["spans_accepted"] == 6 and s["trace_requests"] == 1 and s["last_received_at"]


def test_gzip_and_logs(client, repo):
    body = gzip.compress(log_request("demo-worker", [(1, "ERROR", "x", TRACE, "b1" * 8, {})]).SerializeToString())
    r = client.post("/v1/logs", content=body, headers={**PB, "content-encoding": "gzip"})
    assert r.status_code == 200
    assert repo.get_logs_for_trace(TRACE)[0].body == "x"
    r = client.post("/v1/traces", content=gzip.compress(synthetic_redelivery().SerializeToString()),
                    headers={**PB, "content-encoding": "gzip"})
    assert r.status_code == 200 and len(repo.get_trace(TRACE)) == 6


def test_bad_inputs_never_crash(client):
    assert client.post("/v1/traces", content=b"x", headers={"content-type": "application/json"}).status_code == 415
    assert client.post("/v1/traces", content=b"\xff\xff\xff garbage", headers=PB).status_code == 400
    assert client.post("/v1/logs", content=b"\x0a\xff", headers=PB).status_code == 400
    assert client.post("/v1/traces", content=b"notgzip", headers={**PB, "content-encoding": "gzip"}).status_code == 400
    assert client.post("/v1/traces", content=b"", headers={**PB, "content-encoding": "br"}).status_code == 415
    # empty protobuf is a valid empty export
    assert client.post("/v1/traces", content=b"", headers=PB).status_code == 200
    assert client.get("/api/ingest/stats").json()["rejected_requests"] >= 5


def test_storage_failure_returns_503(client):
    class Broken:
        def save_spans(self, s):
            raise RuntimeError("db down")
    client.app.state.telemetry_repo = Broken()
    r = client.post("/v1/traces", content=synthetic_redelivery().SerializeToString(), headers=PB)
    assert r.status_code == 503
    assert client.get("/api/ingest/stats").json()["storage_errors"] == 1
