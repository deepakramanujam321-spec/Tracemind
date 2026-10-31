"""Correlation tests run on a SYNTHETIC redelivery trace set (see otlp_fixtures.synthetic_redelivery)."""
from datetime import UTC, datetime

import pytest
from otlp_fixtures import (
    S_INS1,
    S_INS2,
    S_P1,
    S_P2,
    TRACE,
    log_request,
    synthetic_redelivery,
)
from tracemind.correlation import EvidenceResolver, detect_incidents
from tracemind.ingest.otlp import parse_logs, parse_traces

EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def load(repo, **kw):
    repo.save_spans(parse_traces(synthetic_redelivery(**kw).SerializeToString()))


def sigs(ctx):
    return {s.name: s for s in ctx.signals}


def test_full_redelivery_duplicate_write(repo):
    load(repo)
    repo.save_logs(parse_logs(log_request("demo-worker", [(58, "ERROR", "ack failure", TRACE, S_P1, {})]).SerializeToString()))
    ctxs = detect_incidents(repo, EPOCH)
    assert len(ctxs) == 1
    c = ctxs[0]
    s = sigs(c)
    assert s["exception_event"].role == "origin"
    assert s["message_redelivered"].role == "transformation"
    assert s["redelivery_duplicate_write"].role == "impact"
    ev = s["redelivery_duplicate_write"].evidence
    assert f"span:{TRACE}:{S_INS1}" in ev and f"span:{TRACE}:{S_INS2}" in ev and f"span:{TRACE}:{S_P2}" in ev
    assert f"event:{TRACE}:{S_P1}:0" in ev
    assert ("demo-api", "demo-worker") in c.edges
    assert c.services == ["demo-api", "demo-worker"]
    assert "No logs correlated" not in " ".join(c.limitations)
    assert [t["time"] for t in c.timeline] == sorted(t["time"] for t in c.timeline)
    # every ref resolves exactly
    res = EvidenceResolver(repo, ctxs)
    for sg in c.signals:
        assert res.is_valid(f"sig:{c.incident_id}:{sg.name}")
        for r in sg.evidence:
            assert res.is_valid(r), r
    for t in c.timeline:
        assert res.is_valid(t["ref"]), t


def test_no_duplicate_claim_without_second_insert(repo):
    load(repo, include_second_insert=False)
    c = detect_incidents(repo, EPOCH)[0]
    assert "redelivery_duplicate_write" not in sigs(c)
    assert any("duplicate write not asserted" in l for l in c.limitations)
    assert any("No logs correlated" in l for l in c.limitations)


def test_no_redelivery_claim_without_attribute(repo):
    load(repo, with_redelivered_attr=False)
    c = detect_incidents(repo, EPOCH)[0]
    assert "redelivery_duplicate_write" not in sigs(c) and "message_redelivered" not in sigs(c)
    assert "repeated_operation" in sigs(c)  # still reported, but only as context
    assert sigs(c)["repeated_operation"].role == "context"


def test_healthy_trace_yields_no_incident(repo):
    from otlp_fixtures import pb_span, trace_request
    repo.save_spans(parse_traces(trace_request({"demo-api": [pb_span("ab" * 16, "cd" * 8, None, "GET /", 0, 5)]}).SerializeToString()))
    assert detect_incidents(repo, EPOCH) == []


def test_partial_trace_limitation(repo):
    from otlp_fixtures import pb_span, trace_request
    t = "ee" * 16
    repo.save_spans(parse_traces(trace_request({"demo-worker": [
        pb_span(t, "01" * 8, "99" * 8, "process", 0, 5, error=True)]}).SerializeToString()))
    c = detect_incidents(repo, EPOCH)[0]
    assert any("not stored" in l for l in c.limitations)


@pytest.mark.parametrize("ref", [
    f"span:{TRACE}:{'0' * 16}", f"span:{'0' * 32}:{S_P1}", f"event:{TRACE}:{S_P1}:7", f"event:{TRACE}:{S_P1}:x",
    "log:999999", "log:abc", "sig:INC-nope:x", "span:bad", "nonsense", "code:r:p:1-2",
])
def test_unresolvable_refs_rejected(repo, ref):
    load(repo)
    assert EvidenceResolver(repo, detect_incidents(repo, EPOCH)).resolve(ref) is None
