"""Sandbox-runnable regression test (no Postgres, no RabbitMQ, no network).

Run from the repo root:  python -m pytest demo/tests/test_sandbox_regression.py
Needs only the worker requirements (demo/worker/requirements.txt) + pytest.

It runs the REAL notif_worker.worker.process_message against an in-memory SQLite database whose
DDL is derived from demo/db/schema.sql, so a UNIQUE constraint/index added there is really
enforced and `ON CONFLICT (notification_id) DO NOTHING` in the worker really works.
"""
import asyncio
import json
import os
import pathlib
import re
import sqlite3
import sys

import pytest

DEMO = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(DEMO / "worker")]
os.environ["FAULT_INJECTION_ENABLED"] = "true"

from notif_worker.worker import InjectedAckFailure, process_message  # noqa: E402,F401


def pg_to_sqlite(ddl: str) -> str:
    """Tiny, deliberately limited Postgres->SQLite DDL translator. Everything not listed is kept as is.

    BIGSERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT; UUID/TIMESTAMPTZ -> TEXT;
    now() -> CURRENT_TIMESTAMP.
    """
    ddl = re.sub(r"\bBIGSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", ddl, flags=re.I)
    ddl = re.sub(r"\b(UUID|TIMESTAMPTZ)\b", "TEXT", ddl, flags=re.I)
    return re.sub(r"\bnow\(\)", "CURRENT_TIMESTAMP", ddl, flags=re.I)


class AsyncSqlite:
    """Just enough of psycopg.AsyncConnection for the worker: execute(sql, params) and commit()."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(pg_to_sqlite((DEMO / "db" / "schema.sql").read_text()))

    async def execute(self, sql, params=()):
        return self.db.execute(sql.replace("%s", "?"), tuple(params))

    async def commit(self):
        self.db.commit()

    def rows(self, nid):
        return self.db.execute("SELECT notification_id FROM notifications WHERE notification_id = ?",
                               (nid,)).fetchall()


class FakeMessage:
    def __init__(self, nid, redelivered=False, fault=None):
        self.body = json.dumps({"notification_id": nid, "user_id": "u-1", "title": "t", "body": "b"}).encode()
        self.headers = {"x-fault": fault} if fault else {}
        self.message_id = nid
        self.redelivered = redelivered
        self.calls = []

    async def ack(self):
        self.calls.append("ack")

    async def nack(self, requeue=True):
        self.calls.append(f"nack(requeue={requeue})")


@pytest.mark.injected_bug
def test_redelivery_is_idempotent_sandbox():
    async def scenario():
        conn, nid = AsyncSqlite(), "11111111-1111-4111-8111-111111111111"
        first = FakeMessage(nid, redelivered=False, fault="ack_failure")
        await process_message(first, conn)
        second = FakeMessage(nid, redelivered=True, fault="ack_failure")
        await process_message(second, conn)
        return conn, nid, first, second

    conn, nid, first, second = asyncio.run(scenario())
    assert first.calls == ["nack(requeue=True)"], "first delivery must be nacked (requeue), never acked"
    assert second.calls == ["ack"], "redelivery must be acked"
    assert len(conn.rows(nid)) == 1, f"expected exactly 1 row for {nid}, got {len(conn.rows(nid))}"


def test_no_fault_single_delivery_one_row():
    async def scenario():
        conn, nid = AsyncSqlite(), "22222222-2222-4222-8222-222222222222"
        msg = FakeMessage(nid)
        await process_message(msg, conn)
        return conn, nid, msg

    conn, nid, msg = asyncio.run(scenario())
    assert msg.calls == ["ack"]
    assert len(conn.rows(nid)) == 1
