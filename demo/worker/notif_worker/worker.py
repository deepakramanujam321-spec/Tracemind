"""Notification worker: consume notifications.create -> insert -> fault check -> ack."""
import asyncio
import json
import logging
import os

import aio_pika
import psycopg
from opentelemetry import trace
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.propagate import extract
from opentelemetry.trace import Link, SpanKind

from .telemetry import setup_telemetry

QUEUE = "notifications.create"
log = logging.getLogger("demo-worker")
tracer = trace.get_tracer("demo-worker")


class InjectedAckFailure(Exception):
    """Deterministic fault: raised after the DB commit and before the ack."""


def _headers(message):
    return {k: (v.decode() if isinstance(v, bytes) else v) for k, v in (message.headers or {}).items()}


async def process_message(message, conn):
    """Handle one delivery. Order matters: insert (commit) -> fault check -> ack."""
    headers = _headers(message)
    body = json.loads(message.body)
    nid = body["notification_id"]
    # Consumer span is linked to (and parented under) the publish context from the traceparent header.
    publish_ctx = extract(headers)
    publish_span_ctx = trace.get_current_span(publish_ctx).get_span_context()
    with tracer.start_as_current_span(
            f"{QUEUE} process", context=publish_ctx, kind=SpanKind.CONSUMER,
            links=[Link(publish_span_ctx)]) as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.destination.name", QUEUE)
        span.set_attribute("messaging.operation.type", "process")
        span.set_attribute("messaging.message.id", message.message_id or nid)
        span.set_attribute("messaging.rabbitmq.message.redelivered", bool(message.redelivered))
        span.set_attribute("notification.id", nid)
        try:
            # 1) INSERT + COMMIT (plain INSERT: no ON CONFLICT, no unique key -- the baseline bug)
            await conn.execute(
                "INSERT INTO notifications (notification_id, user_id, title, body, status) "
                "VALUES (%s, %s, %s, %s, 'delivered')",
                (nid, body["user_id"], body["title"], body["body"]))
            await conn.commit()
            span.set_attribute("notification.status", "delivered")
            log.info("notification persisted id=%s redelivered=%s", nid, message.redelivered)

            # 2) Fault check: after commit, before ack
            fault_on = os.getenv("FAULT_INJECTION_ENABLED", "false").lower() == "true"
            if fault_on and headers.get("x-fault") == "ack_failure" and not message.redelivered:
                with tracer.start_as_current_span("fault.inject") as fspan:
                    fspan.set_attribute("fault.type", "ack_failure")
                    fspan.set_attribute("fault.injected", True)
                    span.set_attribute("fault.injected", True)
                    raise InjectedAckFailure(f"injected ack failure after commit id={nid}")

            # 3) Ack
            await message.ack()
            log.info("notification acked id=%s", nid)
        except InjectedAckFailure as exc:
            # span event 'exception' is recorded by the context managers as the exception propagates;
            # make it explicit on the consumer span too.
            span.record_exception(exc)
            log.error("ack failure injected; nack with requeue id=%s", nid)
            await message.nack(requeue=True)


async def main():
    setup_telemetry("demo-worker")
    PsycopgInstrumentor().instrument()
    conn = await psycopg.AsyncConnection.connect(os.environ["APP_DATABASE_URL"])
    mq = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    channel = await mq.channel()
    await channel.set_qos(prefetch_count=1)
    queue = await channel.declare_queue(QUEUE, durable=True)
    log.info("worker consuming %s", QUEUE)
    async with queue.iterator() as it:
        async for message in it:
            await process_message(message, conn)


if __name__ == "__main__":
    asyncio.run(main())
