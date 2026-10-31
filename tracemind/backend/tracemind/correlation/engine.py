"""Deterministic correlation: traces -> IncidentContext. No LLM, no guessing: every signal cites stored telemetry."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any

from tracemind.contracts import (
    IncidentContext,
    LogRecord,
    Signal,
    Span,
    SpanEvent,
    TelemetryRepository,
)

REDELIVERED = "messaging.rabbitmq.message.redelivered"
ID_KEYS = ("notification.id", "messaging.message.id")
ERROR_SEVERITIES = {"ERROR", "FATAL", "CRITICAL"}


def span_ref(s: Span) -> str:
    return f"span:{s.trace_id}:{s.span_id}"


def event_ref(s: Span, e: SpanEvent) -> str:
    return f"event:{s.trace_id}:{s.span_id}:{e.idx}"


def incident_id_for(trace_id: str) -> str:
    return "INC-" + hashlib.sha1(trace_id.encode()).hexdigest()[:10]


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def _is_db_write(s: Span) -> bool:
    a = s.attributes
    if not a.get("db.system") and not a.get("db.system.name"):
        return False
    op = str(a.get("db.operation") or a.get("db.operation.name") or "").upper()
    stmt = str(a.get("db.statement") or a.get("db.query.text") or "").lstrip().upper()
    nm = s.name.upper()
    return op == "INSERT" or stmt.startswith("INSERT") or nm.startswith("INSERT")


class _Trace:
    def __init__(self, spans: list[Span]):
        self.spans = sorted(spans, key=lambda s: (s.start_time, s.span_id))
        self.by_id = {s.span_id: s for s in self.spans}
        self.children: dict[str, list[Span]] = defaultdict(list)
        self.orphans: list[Span] = []
        self.roots: list[Span] = []
        for s in self.spans:
            if not s.parent_span_id:
                self.roots.append(s)
            elif s.parent_span_id in self.by_id:
                self.children[s.parent_span_id].append(s)
            else:
                self.orphans.append(s)

    def ancestors(self, s: Span):
        seen = set()
        cur = s
        while cur.parent_span_id and cur.parent_span_id in self.by_id and cur.parent_span_id not in seen:
            seen.add(cur.parent_span_id)
            cur = self.by_id[cur.parent_span_id]
            yield cur

    def descendants(self, s: Span):
        stack = list(self.children.get(s.span_id, []))
        while stack:
            c = stack.pop()
            yield c
            stack.extend(self.children.get(c.span_id, []))

    def business_id(self, s: Span) -> str | None:
        for x in (s, *self.ancestors(s)):
            for k in ID_KEYS:
                v = x.attributes.get(k)
                if v:
                    return str(v)
        return None

    def delivery_span(self, s: Span) -> Span | None:
        """Nearest self-or-ancestor span that is a messaging process/consumer span."""
        for x in (s, *self.ancestors(s)):
            if x.attributes.get("messaging.operation.type") == "process" or x.kind == "CONSUMER":
                return x
        return None


def _edges(t: _Trace) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []

    def add(a: str, b: str) -> None:
        if a != b and (a, b) not in edges:
            edges.append((a, b))

    for s in t.spans:
        p = t.by_id.get(s.parent_span_id or "")
        if p:
            add(p.service_name, s.service_name)
    # messaging publish -> process links not expressed through parent/child (match on message id)
    pubs = [s for s in t.spans if s.attributes.get("messaging.operation.type") == "publish" or s.kind == "PRODUCER"]
    procs = [s for s in t.spans if s.attributes.get("messaging.operation.type") == "process" or s.kind == "CONSUMER"]
    for p in pubs:
        pid = p.attributes.get("messaging.message.id") or p.attributes.get("notification.id")
        for c in procs:
            cid = c.attributes.get("messaging.message.id") or c.attributes.get("notification.id")
            if pid and pid == cid:
                add(p.service_name, c.service_name)
    return edges


def analyze_trace(trace_id: str, spans: list[Span], logs: list[LogRecord]) -> IncidentContext | None:
    """Return an IncidentContext if the trace contains failure/anomaly evidence, else None."""
    if not spans:
        return None
    t = _Trace(spans)
    iid = incident_id_for(trace_id)
    limitations: list[str] = []
    sigs: list[Signal] = []

    # --- errors / exceptions -------------------------------------------------
    err_spans = [s for s in t.spans if s.status_code == "ERROR"]
    exc_events = [(s, e) for s in t.spans for e in s.events if e.name == "exception"]
    err_ids = {s.span_id for s in err_spans} | {s.span_id for s, _ in exc_events}

    def is_leaf_failure(s: Span) -> bool:
        return not any(d.span_id in err_ids for d in t.descendants(s))

    origin_spans = [s for s in err_spans if is_leaf_failure(s)]
    prop_spans = [s for s in err_spans if not is_leaf_failure(s)]
    origin_events = [(s, e) for s, e in exc_events if is_leaf_failure(s)]
    prop_events = [(s, e) for s, e in exc_events if not is_leaf_failure(s)]
    if origin_events:
        sigs.append(Signal(
            name="exception_event", role="origin",
            description="Exception recorded on span(s) with no failing descendants: " + "; ".join(
                f"{s.service_name}/{s.name}: {e.attributes.get('exception.type', '?')}" for s, e in origin_events),
            evidence=[event_ref(s, e) for s, e in origin_events] + list(dict.fromkeys(span_ref(x) for x, _ in origin_events))))
    if origin_spans:
        sigs.append(Signal(
            name="error_span", role="origin",
            description="Span(s) with ERROR status and no failing descendants: " + "; ".join(
                f"{s.service_name}/{s.name}" for s in origin_spans),
            evidence=[span_ref(s) for s in origin_spans]))
    if prop_spans or prop_events:
        sigs.append(Signal(
            name="error_propagation", role="transformation",
            description="Failure visible on span(s) that have failing descendants (propagated): " + "; ".join(
                f"{s.service_name}/{s.name}" for s in prop_spans),
            evidence=[span_ref(s) for s in prop_spans] + [event_ref(s, e) for s, e in prop_events]))

    # --- redelivery / repeated operations ------------------------------------
    redelivered = [s for s in t.spans if _truthy(s.attributes.get(REDELIVERED))]
    if redelivered:
        sigs.append(Signal(
            name="message_redelivered", role="transformation",
            description=f"{len(redelivered)} delivery span(s) carry {REDELIVERED}=true for message id(s) "
                        + ", ".join(sorted({t.business_id(s) or '?' for s in redelivered})),
            evidence=[span_ref(s) for s in redelivered]))

    writes = [s for s in t.spans if _is_db_write(s)]
    by_id: dict[str, list[Span]] = defaultdict(list)
    for w in writes:
        bid = t.business_id(w)
        if bid:
            by_id[bid].append(w)
    rep_ev: list[str] = []
    rep_desc: list[str] = []
    for bid, ws in by_id.items():
        if len(ws) >= 2:
            rep_ev += [span_ref(w) for w in ws]
            rep_desc.append(f"{len(ws)} DB INSERT spans for id {bid}")
    if rep_ev:
        sigs.append(Signal(name="repeated_operation", role="context",
                           description="; ".join(rep_desc), evidence=rep_ev))

    dup_ev: list[str] = []
    dup_desc: list[str] = []
    for bid, ws in by_id.items():
        red = [r for r in redelivered if t.business_id(r) == bid]
        if not red:
            continue
        red_ids = {r.span_id for r in red}

        def under_redelivery(w: Span) -> bool:
            return any(x.span_id in red_ids for x in (w, *t.ancestors(w)))

        ok_ws = [w for w in ws if w.status_code != "ERROR"]
        first = [w for w in ok_ws if not under_redelivery(w)]
        again = [w for w in ok_ws if under_redelivery(w)]
        if len(ws) >= 2 and first and again:
            exc_first = [(s, e) for s, e in exc_events
                         if t.business_id(s) == bid and not under_redelivery(s)]
            dup_ev += [span_ref(w) for w in first + again] + [span_ref(r) for r in red]
            dup_ev += [event_ref(s, e) for s, e in exc_first]
            dup_desc.append(
                f"id {bid}: successful INSERT in original delivery and again in redelivery "
                f"(redelivered=true); no telemetry shows the second write being rejected")
        else:
            limitations.append(
                f"Redelivery observed for id {bid} but telemetry does not show successful INSERT spans in both "
                f"the original and redelivered delivery; duplicate write not asserted.")
    if dup_ev:
        sigs.append(Signal(name="redelivery_duplicate_write", role="impact",
                           description="; ".join(dup_desc), evidence=list(dict.fromkeys(dup_ev))))
    elif redelivered and not writes:
        limitations.append("Redelivery observed but no DB write spans in the trace; cannot determine whether work was repeated.")

    # --- logs -----------------------------------------------------------------
    span_keys = {s.span_id for s in t.spans}
    err_logs = [l for l in logs if (l.severity or "").upper() in ERROR_SEVERITIES]
    usable = [l for l in err_logs if l.id is not None]
    if len(usable) != len(err_logs):
        limitations.append("Some error logs have no stored id and cannot be cited.")
    if usable:
        sigs.append(Signal(name="error_log", role="context",
                           description=f"{len(usable)} error-level log record(s) correlated by trace_id",
                           evidence=[f"log:{l.id}" for l in usable]))
    if any(l.span_id and l.span_id not in span_keys for l in logs):
        limitations.append("Some logs reference span ids not present in stored spans.")
    if not logs:
        limitations.append("No logs correlated to this trace (no trace_id-linked log records were stored).")

    if not sigs:
        return None

    # --- structural limitations -------------------------------------------------
    if t.orphans:
        limitations.append(f"{len(t.orphans)} span(s) reference a parent span that is not stored (partial trace).")
    if not t.roots:
        limitations.append("No root span in stored trace; trace is incomplete.")
    consumers = [s for s in t.spans if s.attributes.get("messaging.operation.type") == "process" or s.kind == "CONSUMER"]
    for p in t.spans:
        if p.attributes.get("messaging.operation.type") == "publish" and not consumers:
            limitations.append(f"Publish span {span_ref(p)} has no consumer/process span in the trace.")
            break

    # --- timeline -----------------------------------------------------------------
    tl: list[dict[str, Any]] = []
    for s in t.spans:
        tl.append({"time": s.start_time.isoformat(), "ref": span_ref(s), "service": s.service_name,
                   "what": f"span {s.name} [{s.status_code or 'UNSET'}]"})
        for e in s.events:
            tl.append({"time": e.time.isoformat(), "ref": event_ref(s, e), "service": s.service_name,
                       "what": f"event {e.name}"})
    for l in err_logs:
        if l.id is not None:
            tl.append({"time": l.time.isoformat(), "ref": f"log:{l.id}", "service": l.service_name,
                       "what": f"{l.severity} log"})
    tl.sort(key=lambda x: x["time"])

    services = list(dict.fromkeys(s.service_name for s in t.spans))
    top = next((s for s in sigs if s.name == "redelivery_duplicate_write"), sigs[0])
    title = {
        "redelivery_duplicate_write": "Redelivered message processed twice (duplicate write)",
        "exception_event": "Exception raised during processing",
        "error_span": "Failed span in trace",
    }.get(top.name, f"Anomaly in trace ({top.name})") + f" [{', '.join(services)}]"
    return IncidentContext(incident_id=iid, title=title, trace_ids=[trace_id], services=services,
                           edges=_edges(t), timeline=tl, signals=sigs, limitations=list(dict.fromkeys(limitations)))


def detect_incidents(repo: TelemetryRepository, since: datetime, limit: int = 200) -> list[IncidentContext]:
    out = []
    for tid in repo.recent_trace_ids(since, limit):
        ctx = analyze_trace(tid, repo.get_trace(tid), repo.get_logs_for_trace(tid))
        if ctx:
            out.append(ctx)
    return out


class EvidenceResolver:
    """Resolves span:/event:/log:/sig: refs exactly against stored data. code: refs belong to Team D."""

    def __init__(self, repo: TelemetryRepository, contexts: list[IncidentContext] | None = None):
        self.repo = repo
        self.contexts = {c.incident_id: c for c in contexts or []}

    def register(self, ctx: IncidentContext) -> None:
        self.contexts[ctx.incident_id] = ctx

    def resolve(self, ref: str) -> dict[str, Any] | None:
        try:
            kind, _, rest = ref.partition(":")
            if kind == "span":
                tid, sid = rest.split(":")
                s = next((x for x in self.repo.get_trace(tid) if x.span_id == sid), None)
                return {"ref": ref, "type": "span", "record": s.model_dump(mode="json")} if s else None
            if kind == "event":
                tid, sid, idx = rest.split(":")
                s = next((x for x in self.repo.get_trace(tid) if x.span_id == sid), None)
                e = next((x for x in s.events if x.idx == int(idx)), None) if s else None
                return {"ref": ref, "type": "event", "span": span_ref(s), "record": e.model_dump(mode="json")} if e else None
            if kind == "log":
                if not rest.isdigit():
                    return None
                l = self.repo.get_log(int(rest))
                return {"ref": ref, "type": "log", "record": l.model_dump(mode="json")} if l else None
            if kind == "sig":
                iid, _, name = rest.partition(":")
                c = self.contexts.get(iid)
                sg = next((x for x in c.signals if x.name == name), None) if c else None
                return {"ref": ref, "type": "signal", "record": sg.model_dump(mode="json")} if sg else None
        except (ValueError, TypeError):
            return None
        return None

    def is_valid(self, ref: str) -> bool:
        return self.resolve(ref) is not None
