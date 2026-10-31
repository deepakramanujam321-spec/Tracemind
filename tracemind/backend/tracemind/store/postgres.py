"""Postgres implementation of contracts.TelemetryRepository (psycopg 3, sync)."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from tracemind.contracts import LogRecord, Span, SpanEvent

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def default_dsn() -> str:
    return os.environ.get("TRACEMIND_DATABASE_URL", "postgresql://tracemind:tracemind@localhost:5432/tracemind")


def migrate(dsn: str | None = None, migrations_dir: Path | None = None) -> list[str]:
    """Apply migrations/*.sql in name order, idempotently. Returns files newly recorded."""
    mdir = migrations_dir or MIGRATIONS_DIR
    applied_now: list[str] = []
    with psycopg.connect(dsn or default_dsn(), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(727274)")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
            for f in sorted(mdir.glob("*.sql")):
                if f.name in done:
                    continue
                with conn.transaction():
                    conn.execute(f.read_text())  # migrations are themselves IF NOT EXISTS
                    conn.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))
                applied_now.append(f.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(727274)")
    return applied_now


def _span_from_row(r: dict[str, Any], events: list[SpanEvent]) -> Span:
    return Span(
        trace_id=r["trace_id"], span_id=r["span_id"], parent_span_id=r["parent_span_id"], name=r["name"],
        kind=r["kind"], service_name=r["service_name"], service_version=r["service_version"],
        environment=r["environment"], start_time=r["start_time"], end_time=r["end_time"],
        duration_ms=r["duration_ms"], status_code=r["status_code"], status_message=r["status_message"],
        attributes=r["attributes"], resource=r["resource"], events=events,
    )


class PostgresTelemetryRepository:
    def __init__(self, dsn: str | None = None, min_size: int = 1, max_size: int = 8):
        self.dsn = dsn or default_dsn()
        self.pool = ConnectionPool(self.dsn, min_size=min_size, max_size=max_size, open=True,
                                   kwargs={"row_factory": dict_row})

    def close(self) -> None:
        self.pool.close()

    def save_spans(self, spans: list[Span]) -> int:
        if not spans:
            return 0
        with self.pool.connection() as conn, conn.cursor() as cur:
            for s in spans:
                scope = s.attributes.get("otel.scope.name") if isinstance(s.attributes, dict) else None
                cur.execute(
                    """INSERT INTO spans (trace_id, span_id, parent_span_id, name, kind, service_name, service_version,
                         environment, start_time, end_time, status_code, status_message, attributes, resource, scope_name)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (trace_id, span_id) DO UPDATE SET
                         parent_span_id=EXCLUDED.parent_span_id, name=EXCLUDED.name, kind=EXCLUDED.kind,
                         service_name=EXCLUDED.service_name, service_version=EXCLUDED.service_version,
                         environment=EXCLUDED.environment, start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                         status_code=EXCLUDED.status_code, status_message=EXCLUDED.status_message,
                         attributes=EXCLUDED.attributes, resource=EXCLUDED.resource, scope_name=EXCLUDED.scope_name""",
                    (s.trace_id, s.span_id, s.parent_span_id, s.name, s.kind, s.service_name, s.service_version,
                     s.environment, s.start_time, s.end_time, s.status_code, s.status_message,
                     Jsonb(s.attributes), Jsonb(s.resource), scope),
                )
                cur.execute("DELETE FROM span_events WHERE trace_id=%s AND span_id=%s", (s.trace_id, s.span_id))
                for e in s.events:
                    cur.execute(
                        "INSERT INTO span_events (trace_id, span_id, idx, name, time, attributes) VALUES (%s,%s,%s,%s,%s,%s)",
                        (s.trace_id, s.span_id, e.idx, e.name, e.time, Jsonb(e.attributes)),
                    )
                cur.execute(
                    """INSERT INTO services (name, version, environment, first_seen, last_seen)
                       VALUES (%s,%s,%s,now(),now())
                       ON CONFLICT (name) DO UPDATE SET
                         version=COALESCE(EXCLUDED.version, services.version),
                         environment=COALESCE(EXCLUDED.environment, services.environment),
                         last_seen=now()""",
                    (s.service_name, s.service_version, s.environment),
                )
        return len(spans)

    def save_logs(self, logs: list[LogRecord]) -> int:
        if not logs:
            return 0
        with self.pool.connection() as conn, conn.cursor() as cur:
            for l in logs:
                cur.execute(
                    """INSERT INTO logs (time, trace_id, span_id, service_name, severity, body, attributes)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (l.time, l.trace_id, l.span_id, l.service_name, l.severity, l.body, Jsonb(l.attributes)),
                )
                cur.execute(
                    """INSERT INTO services (name) VALUES (%s)
                       ON CONFLICT (name) DO UPDATE SET last_seen=now()""", (l.service_name,))
        return len(logs)

    def get_trace(self, trace_id: str) -> list[Span]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM spans WHERE trace_id=%s ORDER BY start_time, span_id", (trace_id,)).fetchall()
            evs: dict[str, list[SpanEvent]] = {}
            for e in conn.execute("SELECT * FROM span_events WHERE trace_id=%s ORDER BY span_id, idx", (trace_id,)):
                evs.setdefault(e["span_id"], []).append(
                    SpanEvent(idx=e["idx"], name=e["name"], time=e["time"], attributes=e["attributes"]))
        return [_span_from_row(r, evs.get(r["span_id"], [])) for r in rows]

    @staticmethod
    def _log(r: dict[str, Any]) -> LogRecord:
        return LogRecord(id=r["id"], time=r["time"], trace_id=r["trace_id"], span_id=r["span_id"],
                         service_name=r["service_name"], severity=r["severity"], body=r["body"],
                         attributes=r["attributes"])

    def get_logs_for_trace(self, trace_id: str) -> list[LogRecord]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM logs WHERE trace_id=%s ORDER BY time, id", (trace_id,)).fetchall()
        return [self._log(r) for r in rows]

    def get_log(self, log_id: int) -> LogRecord | None:
        with self.pool.connection() as conn:
            r = conn.execute("SELECT * FROM logs WHERE id=%s", (log_id,)).fetchone()
        return self._log(r) if r else None

    def recent_trace_ids(self, since: datetime, limit: int = 200) -> list[str]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT trace_id FROM spans WHERE start_time >= %s GROUP BY trace_id "
                "ORDER BY max(start_time) DESC LIMIT %s", (since, limit)).fetchall()
        return [r["trace_id"] for r in rows]

    def list_services(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return list(conn.execute("SELECT name, version, environment, first_seen, last_seen FROM services ORDER BY name"))
