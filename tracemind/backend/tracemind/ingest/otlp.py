"""OTLP protobuf -> contracts models. Pure functions, no I/O."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Status

from tracemind.contracts import LogRecord, Span, SpanEvent

KIND = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {Status.STATUS_CODE_UNSET: "UNSET", Status.STATUS_CODE_OK: "OK", Status.STATUS_CODE_ERROR: "ERROR"}


class OtlpDecodeError(ValueError):
    pass


def any_value(v: AnyValue) -> Any:
    k = v.WhichOneof("value")
    if k is None:
        return None
    if k == "string_value":
        return v.string_value
    if k == "bool_value":
        return v.bool_value
    if k == "int_value":
        return v.int_value
    if k == "double_value":
        return v.double_value
    if k == "bytes_value":
        return v.bytes_value.hex()
    if k == "array_value":
        return [any_value(x) for x in v.array_value.values]
    if k == "kvlist_value":
        return {kv.key: any_value(kv.value) for kv in v.kvlist_value.values}
    return None


def attrs(kvs: list[KeyValue]) -> dict[str, Any]:
    return {kv.key: any_value(kv.value) for kv in kvs}


def ts(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def _hex(b: bytes) -> str | None:
    return b.hex() if b else None


def parse_traces(payload: bytes) -> list[Span]:
    req = ExportTraceServiceRequest()
    try:
        req.ParseFromString(payload)
    except Exception as e:  # protobuf DecodeError
        raise OtlpDecodeError(f"invalid ExportTraceServiceRequest: {e}") from e
    out: list[Span] = []
    for rs in req.resource_spans:
        res = attrs(rs.resource.attributes)
        svc = str(res.get("service.name") or "unknown_service")
        for ss in rs.scope_spans:
            for s in ss.spans:
                if len(s.trace_id) != 16 or len(s.span_id) != 8:
                    raise OtlpDecodeError("span with invalid trace_id/span_id length")
                a = attrs(s.attributes)
                if ss.scope.name:
                    a["otel.scope.name"] = ss.scope.name
                if ss.scope.version:
                    a["otel.scope.version"] = ss.scope.version
                if s.trace_state:
                    a["otel.trace_state"] = s.trace_state
                if s.links:
                    a["otel.links"] = [{"trace_id": _hex(l.trace_id), "span_id": _hex(l.span_id),
                                        "attributes": attrs(l.attributes)} for l in s.links]
                start = s.start_time_unix_nano
                end = s.end_time_unix_nano or start
                out.append(Span(
                    trace_id=s.trace_id.hex(), span_id=s.span_id.hex(), parent_span_id=_hex(s.parent_span_id),
                    name=s.name, kind=KIND.get(s.kind, str(s.kind)), service_name=svc,
                    service_version=_s(res.get("service.version")),
                    environment=_s(res.get("deployment.environment") or res.get("deployment.environment.name")),
                    start_time=ts(start), end_time=ts(end),
                    status_code=STATUS.get(s.status.code, "UNSET"), status_message=s.status.message or None,
                    attributes=a, resource=res,
                    events=[SpanEvent(idx=i, name=e.name, time=ts(e.time_unix_nano), attributes=attrs(e.attributes))
                            for i, e in enumerate(s.events)],
                ))
    return out


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def parse_logs(payload: bytes) -> list[LogRecord]:
    req = ExportLogsServiceRequest()
    try:
        req.ParseFromString(payload)
    except Exception as e:
        raise OtlpDecodeError(f"invalid ExportLogsServiceRequest: {e}") from e
    out: list[LogRecord] = []
    for rl in req.resource_logs:
        res = attrs(rl.resource.attributes)
        svc = str(res.get("service.name") or "unknown_service")
        for sl in rl.scope_logs:
            for r in sl.log_records:
                a = attrs(r.attributes)
                if sl.scope.name:
                    a["otel.scope.name"] = sl.scope.name
                a["otel.resource"] = res
                body = any_value(r.body)
                if body is not None and not isinstance(body, str):
                    body = json.dumps(body, default=str)
                t = r.time_unix_nano or r.observed_time_unix_nano
                out.append(LogRecord(
                    time=ts(t), trace_id=_hex(r.trace_id), span_id=_hex(r.span_id), service_name=svc,
                    severity=r.severity_text or None, body=body, attributes=a))
    return out
