"""Telemetry contract checks using in-memory exporters (no collector needed)."""
from conftest import pump_worker

SECRET = {"user_id": "alice-secret", "title": "TOP-SECRET-TITLE", "body": "TOP-SECRET-BODY"}


async def test_spans_logs_and_propagation(api_client, db, channel, spans, logs):
    r = await api_client.post("/api/notifications", json={**SECRET, "fault": "ack_failure"})
    nid = r.json()["notification_id"]
    await pump_worker(channel)
    finished = spans.get_finished_spans()
    by_name = {}
    for s in finished:
        by_name.setdefault(s.name, []).append(s)

    pub = by_name["notifications.create publish"][0]
    assert pub.attributes["messaging.operation.type"] == "publish"
    assert pub.attributes["messaging.system"] == "rabbitmq"
    assert pub.attributes["messaging.destination.name"] == "notifications.create"
    assert pub.attributes["notification.id"] == nid

    procs = by_name["notifications.create process"]
    assert len(procs) == 2
    first, second = sorted(procs, key=lambda s: s.start_time)
    assert first.attributes["messaging.rabbitmq.message.redelivered"] is False
    assert second.attributes["messaging.rabbitmq.message.redelivered"] is True
    for p in procs:
        assert p.attributes["messaging.operation.type"] == "process"
        assert p.attributes["messaging.message.id"] == nid
        # same trace as the publisher + explicit link to the publish span
        assert p.context.trace_id == pub.context.trace_id
        assert p.parent.span_id == pub.context.span_id
        assert p.links[0].context.span_id == pub.context.span_id

    assert first.attributes["fault.injected"] is True
    assert "fault.injected" not in second.attributes
    assert any(e.name == "exception" for e in first.events)
    fault = by_name["fault.inject"][0]
    assert fault.attributes["fault.type"] == "ack_failure"

    assert any(s.name.startswith("INSERT") or "INSERT" in s.name.upper() or
               s.attributes.get("db.system") == "postgresql" for s in finished), "no DB span"

    recs = logs.get_finished_logs()
    assert recs and all(r.log_record.trace_id for r in recs if str(r.log_record.body).startswith("notification "))


async def test_no_pii_in_telemetry(api_client, db, channel, spans, logs):
    await api_client.post("/api/notifications", json={**SECRET, "fault": "ack_failure"})
    await pump_worker(channel)
    blob = " ".join(str(dict(s.attributes)) + str([dict(e.attributes) for e in s.events])
                    for s in spans.get_finished_spans() if not (s.attributes or {}).get("db.system"))
    blob += " ".join(str(r.log_record.body) for r in logs.get_finished_logs())
    for needle in ("TOP-SECRET", "alice-secret"):
        assert needle not in blob
