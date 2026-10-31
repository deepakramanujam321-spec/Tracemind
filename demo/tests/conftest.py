"""Test fixtures. Needs Postgres (db 'app') and RabbitMQ; set APP_DATABASE_URL / RABBITMQ_URL
(defaults target localhost). Tests skip when the services are unreachable."""
import asyncio
import os
import pathlib
import sys

import aio_pika
import psycopg
import pytest
import pytest_asyncio
from opentelemetry.sdk._logs.export import InMemoryLogExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "worker")]

os.environ.setdefault("APP_DATABASE_URL", "postgresql://tracemind:change-me-local-only@localhost:5432/app")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
os.environ["FAULT_INJECTION_ENABLED"] = "true"
os.environ["DEMO_API_NO_AUTOSTART"] = "1"

from notif_worker.telemetry import setup_telemetry  # noqa: E402

SPANS = InMemorySpanExporter()
LOGS = InMemoryLogExporter()
setup_telemetry("demo-test", span_exporter=SPANS, log_exporter=LOGS)


@pytest.fixture(autouse=True)
def clean_telemetry():
    SPANS.clear()
    LOGS.clear()


@pytest.fixture
def spans():
    return SPANS


@pytest.fixture
def logs():
    return LOGS


@pytest_asyncio.fixture
async def db():
    try:
        conn = await psycopg.AsyncConnection.connect(os.environ["APP_DATABASE_URL"], autocommit=True)
    except Exception as exc:
        pytest.skip(f"postgres unavailable: {exc}")
    await conn.execute((ROOT / "db" / "schema.sql").read_text())
    await conn.execute("TRUNCATE notifications")
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def channel():
    try:
        mq = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    except Exception as exc:
        pytest.skip(f"rabbitmq unavailable: {exc}")
    ch = await mq.channel()
    queue = await ch.declare_queue("notifications.create", durable=True)
    await queue.purge()
    yield ch
    await queue.purge()
    await mq.close()


@pytest_asyncio.fixture
async def api_client(db, channel):
    from asgi_lifespan import LifespanManager
    import httpx
    from notif_api.main import create_app
    app = create_app(init_telemetry=False)
    async with LifespanManager(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c


async def pump_worker(channel, max_messages=10):
    """Drive the real worker function over whatever is in the queue (including redeliveries)."""
    from notif_worker.worker import process_message
    queue = await channel.declare_queue("notifications.create", durable=True)
    wconn = await psycopg.AsyncConnection.connect(os.environ["APP_DATABASE_URL"])
    processed = 0
    try:
        for _ in range(max_messages):
            msg = await queue.get(fail=False, timeout=2)
            if msg is None:
                break
            await process_message(msg, wconn)
            processed += 1
    finally:
        await wconn.close()
    return processed
