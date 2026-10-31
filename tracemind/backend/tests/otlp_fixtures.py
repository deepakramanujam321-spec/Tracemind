"""Programmatic OTLP protobuf builders + SYNTHETIC redelivery trace set (test data only, not product code)."""
from __future__ import annotations

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    InstrumentationScope,
    KeyValue,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import Span as PbSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status

T0 = 1_760_000_000_000_000_000  # ns
MS = 1_000_000


def kv(k, v):
    if isinstance(v, bool):
        av = AnyValue(bool_value=v)
    elif isinstance(v, int):
        av = AnyValue(int_value=v)
    elif isinstance(v, float):
        av = AnyValue(double_value=v)
    elif isinstance(v, list):
        av = AnyValue(array_value=ArrayValue(values=[AnyValue(string_value=str(x)) for x in v]))
    else:
        av = AnyValue(string_value=str(v))
    return KeyValue(key=k, value=av)


def resource(service, version="1.0.0", env="demo"):
    return Resource(attributes=[kv("service.name", service), kv("service.version", version),
                                kv("deployment.environment", env)])


def pb_span(trace, span, parent, name, start_ms, end_ms, attrs=None, kind=1, error=False, events=()):
    s = PbSpan(trace_id=bytes.fromhex(trace), span_id=bytes.fromhex(span),
               parent_span_id=bytes.fromhex(parent) if parent else b"", name=name, kind=kind,
               start_time_unix_nano=T0 + start_ms * MS, end_time_unix_nano=T0 + end_ms * MS,
               attributes=[kv(k, v) for k, v in (attrs or {}).items()])
    if error:
        s.status.code = Status.STATUS_CODE_ERROR
        s.status.message = "boom"
    for t_ms, ename, eattrs in events:
        e = s.events.add()
        e.name, e.time_unix_nano = ename, T0 + t_ms * MS
        e.attributes.extend(kv(k, v) for k, v in eattrs.items())
    return s


def trace_request(by_service):
    """by_service: {service_name: [PbSpan]}"""
    req = ExportTraceServiceRequest()
    for svc, spans in by_service.items():
        rs = req.resource_spans.add()
        rs.resource.CopyFrom(resource(svc))
        ss = rs.scope_spans.add()
        ss.scope.CopyFrom(InstrumentationScope(name="test.scope", version="0.1"))
        ss.spans.extend(spans)
    return req


def log_request(service, records):
    """records: [(ms, severity, body, trace_hex, span_hex, attrs)]"""
    req = ExportLogsServiceRequest()
    rl = req.resource_logs.add()
    rl.resource.CopyFrom(resource(service))
    sl = rl.scope_logs.add()
    for ms, sev, body, tr, sp, at in records:
        r = sl.log_records.add()
        r.time_unix_nano = T0 + ms * MS
        r.severity_text = sev
        r.body.string_value = body
        if tr:
            r.trace_id = bytes.fromhex(tr)
        if sp:
            r.span_id = bytes.fromhex(sp)
        r.attributes.extend(kv(k, v) for k, v in (at or {}).items())
    return req


TRACE = "0af7651916cd43dd8448eb211c80319c"
NID = "11111111-2222-4333-8444-555555555555"
# span ids
S_API, S_PUB, S_P1, S_INS1, S_P2, S_INS2 = ("a1" * 8, "a2" * 8, "b1" * 8, "b2" * 8, "c1" * 8, "c2" * 8)


def synthetic_redelivery(include_second_insert=True, with_redelivered_attr=True):
    """SYNTHETIC: api publish -> worker process (insert, then injected ack failure) -> redelivery (insert again)."""
    msg = {"messaging.system": "rabbitmq", "messaging.destination.name": "notifications.create",
           "messaging.message.id": NID, "notification.id": NID}
    api = [
        pb_span(TRACE, S_API, None, "POST /api/notifications", 0, 20, {"notification.id": NID}, kind=2),
        pb_span(TRACE, S_PUB, S_API, "notifications.create publish", 5, 10,
                {**msg, "messaging.operation.type": "publish"}, kind=4),
    ]
    worker = [
        pb_span(TRACE, S_P1, S_PUB, "notifications.create process", 30, 60,
                {**msg, "messaging.operation.type": "process", "messaging.rabbitmq.message.redelivered": False,
                 "fault.injected": True}, kind=5, error=True,
                events=[(58, "exception", {"exception.type": "InjectedAckFailure", "exception.message": "ack failure"})]),
        pb_span(TRACE, S_INS1, S_P1, "INSERT notifications", 40, 45, {"db.system": "postgresql", "db.operation": "INSERT"}, kind=3),
        pb_span(TRACE, S_P2, S_PUB, "notifications.create process", 100, 130,
                {**msg, "messaging.operation.type": "process",
                 "messaging.rabbitmq.message.redelivered": with_redelivered_attr}, kind=5),
    ]
    if include_second_insert:
        worker.append(pb_span(TRACE, S_INS2, S_P2, "INSERT notifications", 110, 115,
                              {"db.system": "postgresql", "db.operation": "INSERT"}, kind=3))
    return trace_request({"demo-api": api, "demo-worker": worker})
