from datetime import UTC, datetime, timedelta

import psycopg
from otlp_fixtures import NID, S_INS1, TRACE, log_request, synthetic_redelivery
from tracemind.ingest.otlp import parse_logs, parse_traces
from tracemind.store import migrate


def test_migrate_is_idempotent(migrated):
    assert migrate(migrated) == []  # already applied by fixture
    assert migrate(migrated) == []
    with psycopg.connect(migrated) as c:
        assert c.execute("SELECT count(*) FROM schema_migrations WHERE name='001_init.sql'").fetchone()[0] == 1


def test_span_roundtrip_preserves_everything(repo):
    spans = parse_traces(synthetic_redelivery().SerializeToString())
    assert repo.save_spans(spans) == 6
    got = {s.span_id: s for s in repo.get_trace(TRACE)}
    p1 = got["b1" * 8]
    assert p1.parent_span_id == "a2" * 8 and p1.service_name == "demo-worker" and p1.service_version == "1.0.0"
    assert p1.status_code == "ERROR" and p1.status_message == "boom" and p1.kind == "CONSUMER"
    assert p1.attributes["fault.injected"] is True
    assert p1.attributes["messaging.rabbitmq.message.redelivered"] is False
    assert p1.attributes["otel.scope.name"] == "test.scope"
    assert p1.resource["deployment.environment"] == "demo"
    assert p1.events[0].name == "exception" and p1.events[0].idx == 0
    assert p1.events[0].attributes["exception.type"] == "InjectedAckFailure"
    assert p1.duration_ms == 30.0
    assert got["a1" * 8].parent_span_id is None
    assert got[S_INS1].attributes["db.operation"] == "INSERT"


def test_save_spans_upsert_no_duplicates(repo):
    spans = parse_traces(synthetic_redelivery().SerializeToString())
    repo.save_spans(spans)
    repo.save_spans(spans)
    got = repo.get_trace(TRACE)
    assert len(got) == 6
    assert sum(len(s.events) for s in got) == 1


def test_services_upserted(repo):
    repo.save_spans(parse_traces(synthetic_redelivery().SerializeToString()))
    names = [s["name"] for s in repo.list_services()]
    assert names == ["demo-api", "demo-worker"]
    assert repo.list_services()[0]["version"] == "1.0.0"


def test_logs_and_recent_traces(repo):
    repo.save_spans(parse_traces(synthetic_redelivery().SerializeToString()))
    logs = parse_logs(log_request("demo-worker", [(50, "ERROR", "failed " + NID, TRACE, "b1" * 8, {"k": 1}),
                                                  (51, "INFO", "other", None, None, None)]).SerializeToString())
    assert repo.save_logs(logs) == 2
    got = repo.get_logs_for_trace(TRACE)
    assert len(got) == 1 and got[0].severity == "ERROR" and got[0].attributes["k"] == 1 and got[0].id
    assert repo.get_log(got[0].id).body == "failed " + NID
    assert repo.get_log(10**9) is None
    old = datetime(2000, 1, 1, tzinfo=UTC)
    assert repo.recent_trace_ids(old) == [TRACE]
    assert repo.recent_trace_ids(datetime.now(UTC) + timedelta(days=1)) == []
