"""Shared cross-team contracts. Orchestrator-owned; see docs/ARCHITECTURE.md. Change docs first."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

# ---- Evidence refs: span:<trace>:<span> | event:<trace>:<span>:<idx> | log:<id> | code:<repo>:<path>:<a>-<b> | sig:<incident>:<name>
EvidenceRef = str
Validation = Literal["supported", "rejected", "inconclusive"]
Certainty = Literal["confirmed", "suspected", "inconclusive"]


class Span(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: str | None = None
    service_name: str
    service_version: str | None = None
    environment: str | None = None
    start_time: datetime
    end_time: datetime
    duration_ms: float | None = None
    status_code: str | None = None  # UNSET | OK | ERROR
    status_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)


class SpanEvent(BaseModel):
    idx: int
    name: str
    time: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)


class LogRecord(BaseModel):
    id: int | None = None
    time: datetime
    trace_id: str | None = None
    span_id: str | None = None
    service_name: str
    severity: str | None = None
    body: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


Span.model_rebuild()


class TelemetryRepository(Protocol):
    """Storage seam (Postgres now, ClickHouse later). Sync or async is Team B's call; keep it uniform."""

    def save_spans(self, spans: list[Span]) -> int: ...
    def save_logs(self, logs: list[LogRecord]) -> int: ...
    def get_trace(self, trace_id: str) -> list[Span]: ...
    def get_logs_for_trace(self, trace_id: str) -> list[LogRecord]: ...
    def get_log(self, log_id: int) -> LogRecord | None: ...
    def recent_trace_ids(self, since: datetime, limit: int = 200) -> list[str]: ...
    def list_services(self) -> list[dict[str, Any]]: ...


class Signal(BaseModel):
    """Deterministic correlation finding. Ref = sig:<incident_id>:<name>."""
    name: str                       # e.g. redelivery_duplicate_write, error_span, exception_event
    description: str
    evidence: list[EvidenceRef]     # span/event/log refs backing it
    role: Literal["origin", "transformation", "impact", "context"] = "context"


class IncidentContext(BaseModel):
    incident_id: str
    title: str
    trace_ids: list[str]
    services: list[str]
    edges: list[tuple[str, str]]    # caller -> callee service dependencies
    timeline: list[dict[str, Any]]  # [{time, ref, service, what}]
    signals: list[Signal]
    limitations: list[str] = Field(default_factory=list)  # missing telemetry, stated explicitly


class Hypothesis(BaseModel):
    id: str
    author_agent: str
    description: str
    confidence: float = Field(ge=0, le=1)  # model estimate, NOT a probability
    supporting_refs: list[EvidenceRef] = Field(default_factory=list)
    contradicting_refs: list[EvidenceRef] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    challenges: list[dict[str, Any]] = Field(default_factory=list)
    validation_status: Validation = "inconclusive"


class CodeFinding(BaseModel):
    ref: EvidenceRef                # code:<repo>:<path>:<a>-<b>, must resolve to real file lines
    symbol: str | None = None
    note: str


class CodeIntelligence(Protocol):
    """Team D implements; Team C consumes. Graphify-backed with labelled fallback."""
    backend: Literal["graphify", "fallback"]

    def find_candidates(self, repo_id: str, query: str, limit: int = 10) -> list[CodeFinding]: ...
    def read_source(self, repo_id: str, path: str, start: int, end: int) -> str: ...
    def related(self, repo_id: str, symbol: str) -> list[CodeFinding]: ...  # callers/callees/neighbours


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelProvider(Protocol):
    name: str
    supports_tools: bool

    def generate(self, messages: list[Message], **opts: Any) -> str: ...
    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts: Any) -> BaseModel: ...
