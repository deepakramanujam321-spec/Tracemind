"""Notification API: POST /api/notifications publishes to RabbitMQ; GET reads the inbox."""
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

import aio_pika
import psycopg
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind
from psycopg.rows import dict_row
from pydantic import BaseModel

from .telemetry import setup_telemetry

QUEUE = "notifications.create"
log = logging.getLogger("demo-api")
tracer = trace.get_tracer("demo-api")


class NotificationIn(BaseModel):
    user_id: str
    title: str
    body: str
    fault: Optional[Literal["ack_failure"]] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mq = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    app.state.channel = await app.state.mq.channel()
    await app.state.channel.declare_queue(QUEUE, durable=True)
    yield
    await app.state.mq.close()


def create_app(init_telemetry: bool = True) -> FastAPI:
    if init_telemetry:
        setup_telemetry("demo-api")
    PsycopgInstrumentor().instrument()
    app = FastAPI(title="demo-api", lifespan=lifespan)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/api/notifications", status_code=202)
    async def create_notification(n: NotificationIn):
        notification_id = str(uuid.uuid4())
        headers = {}
        if n.fault and os.getenv("FAULT_INJECTION_ENABLED", "false").lower() == "true":
            headers["x-fault"] = n.fault
        payload = {"notification_id": notification_id, "user_id": n.user_id,
                   "title": n.title, "body": n.body}
        with tracer.start_as_current_span(f"{QUEUE} publish", kind=SpanKind.PRODUCER) as span:
            span.set_attribute("messaging.system", "rabbitmq")
            span.set_attribute("messaging.destination.name", QUEUE)
            span.set_attribute("messaging.operation.type", "publish")
            span.set_attribute("messaging.message.id", notification_id)
            span.set_attribute("notification.id", notification_id)
            span.set_attribute("notification.status", "queued")
            inject(headers)  # W3C traceparent / tracestate into AMQP headers
            await app.state.channel.default_exchange.publish(
                aio_pika.Message(body=json.dumps(payload).encode(), headers=headers,
                                 message_id=notification_id,
                                 content_type="application/json",
                                 delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=QUEUE)
            log.info("notification queued id=%s fault=%s", notification_id, headers.get("x-fault"))
        return {"notification_id": notification_id, "status": "queued"}

    @app.get("/api/notifications")
    async def list_notifications(user_id: str):
        async with await psycopg.AsyncConnection.connect(
                os.environ["APP_DATABASE_URL"], row_factory=dict_row) as conn:
            cur = await conn.execute(
                "SELECT id, notification_id::text AS notification_id, user_id, title, body, status, "
                "created_at FROM notifications WHERE user_id = %s ORDER BY id", (user_id,))
            rows = await cur.fetchall()
        for r in rows:
            r["created_at"] = r["created_at"].isoformat()
        return rows

    return app


app = create_app() if os.getenv("DEMO_API_NO_AUTOSTART") != "1" else None
