/**
 * FIXTURE DATA — only loaded when the URL has ?fixtures=1 (see api/client.ts).
 * Models the demo incident from docs/ARCHITECTURE.md §3: an injected ack failure
 * causes RabbitMQ redelivery and the non-idempotent worker INSERT writes a duplicate row.
 * Nothing in here is ever shown unless the persistent FIXTURE DATA banner is visible.
 */
import type {
  AgentStep,
  CommandRun,
  Hypothesis,
  IncidentContext,
  IncidentDetail,
  InvestigationSummary,
  LogRecord,
  Remediation,
  ServiceInfo,
  Span,
  TestResult,
  Adjudication,
} from '../api/types'

const T0 = Date.parse('2026-10-31T10:14:02.000Z')
const at = (ms: number) => new Date(T0 + ms).toISOString()

export const TRACE_ID = '4bf92f3577b34da6a3ce929d0e0e4736'
export const INCIDENT_ID = 'inc-7f3a21'
export const INVESTIGATION_ID = 'inv-3c9e10'
export const REMEDIATION_ID = 'rem-91b4d2'
export const NOTIFICATION_ID = '5d1c0b8e-3a52-4f0e-9a43-2b6c7e91d0aa'
export const REPO_ID = 'demo-notifications'
const SHA = '8d159cb4e0a1f6b72c3d9e5a1b0f47d2c8e6a931'

const S = {
  api: 'a1b2c3d4e5f60001',
  pub: 'a1b2c3d4e5f60002',
  w1: 'b7c8d9e0f1a20001',
  w1db: 'b7c8d9e0f1a20002',
  w2: 'b7c8d9e0f1a20003',
  w2db: 'b7c8d9e0f1a20004',
}
const sref = (id: string) => `span:${TRACE_ID}:${id}`

const apiRes = { 'service.name': 'demo-api', 'service.version': '0.1.0', 'deployment.environment': 'demo' }
const wkRes = { 'service.name': 'demo-worker', 'service.version': '0.1.0', 'deployment.environment': 'demo' }

function span(p: Partial<Span> & Pick<Span, 'span_id' | 'name' | 'service_name'>, start: number, dur: number): Span {
  return {
    trace_id: TRACE_ID,
    parent_span_id: null,
    kind: 'INTERNAL',
    service_version: '0.1.0',
    environment: 'demo',
    start_time: at(start),
    end_time: at(start + dur),
    duration_ms: dur,
    status_code: 'OK',
    status_message: null,
    attributes: {},
    resource: p.service_name === 'demo-api' ? apiRes : wkRes,
    events: [],
    ...p,
  }
}

export const SPANS: Span[] = [
  span(
    {
      span_id: S.api, name: 'POST /api/notifications', service_name: 'demo-api', kind: 'SERVER',
      attributes: { 'http.request.method': 'POST', 'http.route': '/api/notifications', 'http.response.status_code': 202, 'notification.id': NOTIFICATION_ID },
    }, 0, 42),
  span(
    {
      span_id: S.pub, parent_span_id: S.api, name: 'notifications.create publish', service_name: 'demo-api', kind: 'PRODUCER',
      attributes: { 'messaging.system': 'rabbitmq', 'messaging.destination.name': 'notifications.create', 'messaging.operation.type': 'publish', 'messaging.message.id': NOTIFICATION_ID, 'notification.id': NOTIFICATION_ID },
    }, 9, 21),
  span(
    {
      span_id: S.w1, parent_span_id: S.pub, name: 'notifications.create process', service_name: 'demo-worker', kind: 'CONSUMER',
      status_code: 'ERROR', status_message: 'InjectedAckFailure: ack lost after commit',
      attributes: { 'messaging.system': 'rabbitmq', 'messaging.destination.name': 'notifications.create', 'messaging.operation.type': 'process', 'messaging.message.id': NOTIFICATION_ID, 'messaging.rabbitmq.message.redelivered': false, 'notification.id': NOTIFICATION_ID, 'fault.injected': true },
      events: [
        { idx: 0, name: 'exception', time: at(176), attributes: { 'exception.type': 'InjectedAckFailure', 'exception.message': 'ack lost after commit', 'exception.stacktrace': 'Traceback (most recent call last):\n  File "worker/consumer.py", line 42, in on_message\n    raise err\nworker.faults.InjectedAckFailure: ack lost after commit' } },
      ],
    }, 38, 142),
  span(
    {
      span_id: S.w1db, parent_span_id: S.w1, name: 'INSERT notifications', service_name: 'demo-worker', kind: 'CLIENT',
      attributes: { 'db.system': 'postgresql', 'db.operation': 'INSERT', 'db.sql.table': 'notifications', 'notification.id': NOTIFICATION_ID },
    }, 61, 38),
  span(
    {
      span_id: S.w2, parent_span_id: S.pub, name: 'notifications.create process', service_name: 'demo-worker', kind: 'CONSUMER',
      attributes: { 'messaging.system': 'rabbitmq', 'messaging.destination.name': 'notifications.create', 'messaging.operation.type': 'process', 'messaging.message.id': NOTIFICATION_ID, 'messaging.rabbitmq.message.redelivered': true, 'notification.id': NOTIFICATION_ID, 'notification.status': 'delivered' },
    }, 1204, 96),
  span(
    {
      span_id: S.w2db, parent_span_id: S.w2, name: 'INSERT notifications', service_name: 'demo-worker', kind: 'CLIENT',
      attributes: { 'db.system': 'postgresql', 'db.operation': 'INSERT', 'db.sql.table': 'notifications', 'notification.id': NOTIFICATION_ID },
    }, 1229, 34),
]

export const LOGS: LogRecord[] = [
  { id: 101, time: at(12), trace_id: TRACE_ID, span_id: S.api, service_name: 'demo-api', severity: 'INFO', body: `queued notification ${NOTIFICATION_ID} fault=ack_failure`, attributes: {} },
  { id: 102, time: at(55), trace_id: TRACE_ID, span_id: S.w1, service_name: 'demo-worker', severity: 'INFO', body: `processing notification ${NOTIFICATION_ID}`, attributes: {} },
  { id: 103, time: at(176), trace_id: TRACE_ID, span_id: S.w1, service_name: 'demo-worker', severity: 'ERROR', body: 'InjectedAckFailure: ack lost after commit; nacking with requeue, message not acked', attributes: {} },
  { id: 104, time: at(1212), trace_id: TRACE_ID, span_id: S.w2, service_name: 'demo-worker', severity: 'INFO', body: `processing notification ${NOTIFICATION_ID}`, attributes: {} },
  { id: 105, time: at(1292), trace_id: TRACE_ID, span_id: S.w2, service_name: 'demo-worker', severity: 'INFO', body: `notification ${NOTIFICATION_ID} delivered`, attributes: {} },
]

const sig = (n: string) => `sig:${INCIDENT_ID}:${n}`

export const CONTEXT: IncidentContext = {
  incident_id: INCIDENT_ID,
  title: 'Duplicate notification after message redelivery',
  trace_ids: [TRACE_ID],
  services: ['demo-api', 'rabbitmq', 'demo-worker', 'postgres'],
  edges: [['demo-api', 'rabbitmq'], ['rabbitmq', 'demo-worker'], ['demo-worker', 'postgres']],
  timeline: [
    { time: at(12), ref: 'log:101', service: 'demo-api', what: 'Notification queued with fault header ack_failure' },
    { time: at(61), ref: sref(S.w1db), service: 'demo-worker', what: 'First delivery: INSERT notifications committed (redelivered=false)' },
    { time: at(176), ref: `event:${TRACE_ID}:${S.w1}:0`, service: 'demo-worker', what: 'InjectedAckFailure raised after commit; message nacked with requeue' },
    { time: at(1204), ref: sref(S.w2), service: 'demo-worker', what: 'Broker redelivered the same message (redelivered=true)' },
    { time: at(1229), ref: sref(S.w2db), service: 'demo-worker', what: 'Second INSERT notifications for the same notification.id' },
    { time: at(1300), ref: sig('duplicate_row_written'), service: 'demo-worker', what: 'Two rows now exist for one notification_id (impact)' },
  ],
  signals: [
    { name: 'publish_once', role: 'context', description: 'Exactly one publish span exists for this notification; the producer did not send it twice.', evidence: [sref(S.pub)] },
    { name: 'exception_event', role: 'transformation', description: 'InjectedAckFailure recorded on the first process span after the DB commit and before ack.', evidence: [`event:${TRACE_ID}:${S.w1}:0`, 'log:103'] },
    { name: 'redelivery_duplicate_write', role: 'origin', description: 'Two INSERT spans with identical notification.id, the second under a process span with redelivered=true.', evidence: [sref(S.w1db), sref(S.w2), sref(S.w2db)] },
    { name: 'duplicate_row_written', role: 'impact', description: 'Second INSERT succeeded without conflict handling, so a duplicate inbox row is persisted.', evidence: [sref(S.w2db)] },
  ],
  limitations: [
    'Row contents of the notifications table are not part of ingested telemetry; duplication is inferred from the two INSERT spans.',
    'No RabbitMQ or Postgres server-side telemetry; those nodes are inferred from messaging/db span attributes.',
  ],
}

export const SERVICES: ServiceInfo[] = [
  { name: 'demo-api', version: '0.1.0', environment: 'demo', span_count: 2, error_count: 0, last_seen: at(42) },
  { name: 'demo-worker', version: '0.1.0', environment: 'demo', span_count: 4, error_count: 1, last_seen: at(1300) },
]

export const INCIDENT_SUMMARY = {
  id: INCIDENT_ID,
  title: CONTEXT.title,
  status: 'investigating' as const,
  severity: 'high' as const,
  services: ['demo-api', 'demo-worker'],
  trace_ids: [TRACE_ID],
  signal_count: CONTEXT.signals.length,
  first_seen: at(0),
  last_seen: at(1300),
}

export const INVESTIGATION_SUMMARY: InvestigationSummary = {
  id: INVESTIGATION_ID,
  incident_id: INCIDENT_ID,
  incident_title: CONTEXT.title,
  status: 'completed',
  certainty: 'confirmed',
  started_at: at(60_000),
  finished_at: at(94_000),
}

export const INCIDENT_DETAIL: IncidentDetail = {
  ...INCIDENT_SUMMARY,
  context: CONTEXT,
  investigations: [INVESTIGATION_SUMMARY],
}

const codeConsumer = `code:${REPO_ID}:demo/worker/worker/consumer.py`
const codeSchema = `code:${REPO_ID}:demo/db/schema.sql`
export const CODE_INSERT = `${codeConsumer}:15-25`
export const CODE_ACK = `${codeConsumer}:36-42`
export const CODE_SCHEMA = `${codeSchema}:1-9`

export const HYPOTHESES: Hypothesis[] = [
  {
    id: 'H1', author_agent: 'hypothesizer_a', confidence: 0.88, validation_status: 'supported',
    description: 'The worker committed the INSERT, then failed before acking. RabbitMQ redelivered the unacked message and the worker re-ran the same non-idempotent INSERT, persisting a duplicate.',
    supporting_refs: [sref(S.w1db), `event:${TRACE_ID}:${S.w1}:0`, sref(S.w2), sref(S.w2db), sig('redelivery_duplicate_write'), CODE_ACK],
    contradicting_refs: [],
    alternatives: ['Producer published the message twice'],
    missing_evidence: ['Direct inspection of the notifications table'],
    challenges: [
      { by: 'skeptic', challenge: 'Are the two INSERT spans distinct statements rather than one retried inside the same transaction?', response: 'They have different span ids under different process spans, and the first ends 0.14 s before the exception event.', outcome: 'withdrawn' },
      { by: 'skeptic', challenge: 'Duplicate rows are inferred from spans, never observed in the table.', response: 'Cannot be resolved from telemetry alone; remediation includes a regression test that counts rows.', outcome: 'unresolved' },
    ],
  },
  {
    id: 'H2', author_agent: 'hypothesizer_b', confidence: 0.79, validation_status: 'supported',
    description: 'The notifications table has no UNIQUE(notification_id) and the INSERT has no conflict handling, so any repeated delivery of a message is persisted as a new row.',
    supporting_refs: [CODE_SCHEMA, CODE_INSERT, sref(S.w2db)],
    contradicting_refs: [],
    alternatives: ['A unique index exists elsewhere in the database not shown in schema.sql'],
    missing_evidence: ['Live database schema (only the repository DDL was inspected)'],
    challenges: [
      { by: 'skeptic', challenge: 'A missing constraint explains persistence but not why a second delivery happened at all.', response: 'Accepted: this is a contributing cause. The delivery trigger is covered by H1.', outcome: 'upheld' },
    ],
  },
  {
    id: 'H3', author_agent: 'hypothesizer_c', confidence: 0.22, validation_status: 'rejected',
    description: 'demo-api published the notification twice, producing two independent messages that each inserted a row.',
    supporting_refs: ['log:104'],
    contradicting_refs: [sref(S.pub), sig('publish_once'), sref(S.w2)],
    alternatives: [],
    missing_evidence: [],
    challenges: [
      { by: 'skeptic', challenge: 'Two "processing" logs for one id do not imply two publishes.', response: 'Only one publish span exists and the second process span carries redelivered=true.', outcome: 'upheld' },
    ],
  },
]

export const ADJUDICATION: Adjudication = {
  certainty: 'confirmed',
  winning_hypothesis_id: 'H1',
  root_cause: 'Redelivery after a lost ack replays a non-idempotent INSERT. The worker commits before acking, and the table has no uniqueness guard on notification_id, so the replay creates a duplicate row.',
  rationale: 'H1 is backed by a deterministic chain of resolved span, event and signal references (commit, exception, redelivered=true, second INSERT). H2 identifies the missing guard that lets the replay persist and is merged as a contributing cause. H3 is contradicted by the single publish span and the redelivered flag.',
  rejected_hypothesis_ids: ['H3'],
  evidence_refs: [sref(S.w1db), `event:${TRACE_ID}:${S.w1}:0`, sref(S.w2), sref(S.w2db), CODE_ACK, CODE_SCHEMA],
  limitations: [
    'Table contents were not observed; duplicate rows are inferred from two INSERT spans with the same notification.id.',
  ],
  rejected_refs: [],
}

const step = (i: number, agent: string, role: string, ms: number, dur: number, summary: string, refs: string[] = []): AgentStep => ({
  id: `step-${i}`, agent, role, status: 'completed',
  started_at: at(60_000 + ms), finished_at: at(60_000 + ms + dur), summary, evidence_refs: refs, error: null,
})

export const STEPS: AgentStep[] = [
  step(1, 'context_builder', 'Incident context', 0, 1800, 'Loaded 1 trace, 6 spans, 5 logs and 4 deterministic signals. 2 limitations recorded.', [sig('redelivery_duplicate_write')]),
  step(2, 'telemetry_agent', 'Telemetry analysis', 1800, 9200, 'Second process span carries redelivered=true; both INSERT spans share notification.id. Exception event precedes the redelivery.', [`event:${TRACE_ID}:${S.w1}:0`, sref(S.w2)]),
  step(3, 'code_agent', 'Code localisation', 11_000, 7400, 'Graphify located on_message and insert_notification; plain INSERT with no conflict clause; no UNIQUE constraint in schema.', [CODE_INSERT, CODE_SCHEMA]),
  step(4, 'hypothesizer_a', 'Independent hypothesis', 18_400, 6100, 'Proposed H1 (redelivery replays non-idempotent INSERT).'),
  step(5, 'hypothesizer_b', 'Independent hypothesis', 18_400, 6900, 'Proposed H2 (missing uniqueness guard).'),
  step(6, 'hypothesizer_c', 'Independent hypothesis', 18_400, 5800, 'Proposed H3 (producer double publish).'),
  step(7, 'skeptic', 'Skeptic review', 25_300, 8100, 'Raised 4 challenges across 3 hypotheses; 1 withdrawn, 2 upheld, 1 unresolved.'),
  step(8, 'evidence_validator', 'Reference validation', 33_400, 900, 'Resolved 19 of 19 cited references against stored telemetry and repository files. 0 rejected.'),
  step(9, 'adjudicator', 'Adjudication', 34_300, 3200, 'H1 confirmed as trigger, H2 merged as contributing cause, H3 rejected.'),
]

export const DIFF = `diff --git a/demo/db/002_notification_id_unique.sql b/demo/db/002_notification_id_unique.sql
new file mode 100644
--- /dev/null
+++ b/demo/db/002_notification_id_unique.sql
@@ -0,0 +1,8 @@
+-- Remove existing duplicates, keeping the earliest row per notification_id.
+DELETE FROM notifications a
+USING notifications b
+WHERE a.notification_id = b.notification_id
+  AND a.id > b.id;
+
+ALTER TABLE notifications
+    ADD CONSTRAINT notifications_notification_id_key UNIQUE (notification_id);
diff --git a/demo/worker/worker/consumer.py b/demo/worker/worker/consumer.py
--- a/demo/worker/worker/consumer.py
+++ b/demo/worker/worker/consumer.py
@@ -19,7 +19,8 @@ def insert_notification(conn, msg: dict) -> None:
         with conn.cursor() as cur:
             cur.execute(
                 "INSERT INTO notifications (notification_id, user_id, title, body, status) "
-                "VALUES (%s, %s, %s, %s, 'delivered')",
+                "VALUES (%s, %s, %s, %s, 'delivered') "
+                "ON CONFLICT (notification_id) DO NOTHING",
                 (msg["notification_id"], msg["user_id"], msg["title"], msg["body"]),
             )
         conn.commit()
`

const cmd = (i: number, phase: string, command: string, exit: number, dur: number, out: string, err = ''): CommandRun => ({
  id: `cmd-${i}`, phase, command, exit_code: exit, duration_ms: dur, stdout: out, stderr: err, started_at: at(200_000 + i * 4000),
})

export const COMMANDS: CommandRun[] = [
  cmd(1, 'baseline', 'pytest demo/tests -k test_redelivery_is_idempotent -q', 1, 3120,
    'F                                                                        [100%]\n=================================== FAILURES ===================================\n__________________________ test_redelivery_is_idempotent _______________________\n>       assert rows == 1\nE       assert 2 == 1\n1 failed in 2.84s'),
  cmd(2, 'apply', 'git apply --check patch.diff && git apply patch.diff', 0, 180, ''),
  cmd(3, 'test', 'pytest demo/tests -q', 0, 5870, '.......                                                                  [100%]\n7 passed in 5.41s'),
  cmd(4, 'regression', 'pytest demo/tests -k test_redelivery_is_idempotent -q', 0, 3010, '.                                                                        [100%]\n1 passed in 2.71s'),
]

export const TESTS: TestResult[] = [
  { name: 'demo/tests/test_worker.py::test_redelivery_is_idempotent', outcome: 'failed', phase: 'baseline', detail: 'assert 2 == 1' },
  { name: 'demo/tests/test_worker.py::test_redelivery_is_idempotent', outcome: 'passed', phase: 'after_patch', detail: null },
  { name: 'demo/tests/test_api.py::test_enqueue_returns_202', outcome: 'passed', phase: 'after_patch', detail: null },
  { name: 'demo/tests/test_worker.py::test_normal_delivery_inserts_once', outcome: 'passed', phase: 'after_patch', detail: null },
]

export const REMEDIATION: Remediation = {
  id: REMEDIATION_ID,
  investigation_id: INVESTIGATION_ID,
  incident_id: INCIDENT_ID,
  status: 'verified',
  repository_id: REPO_ID,
  base_sha: SHA,
  source_refs: [CODE_INSERT, CODE_SCHEMA],
  summary: 'Add UNIQUE(notification_id) via a cleanup+constraint migration and make the worker INSERT idempotent with ON CONFLICT DO NOTHING.',
  diff: DIFF,
  command_runs: COMMANDS,
  test_results: TESTS,
  error: null,
  approved: false,
  approved_by: null,
  approved_at: null,
  created_at: at(198_000),
}

// ---- repository files for code: evidence resolution ----
export const FILES: Record<string, string> = {
  'demo/worker/worker/consumer.py': `import json
import logging
import os

import pika
from opentelemetry import trace

from worker.db import get_conn
from worker.faults import InjectedAckFailure, fault_enabled

log = logging.getLogger("demo-worker")
tracer = trace.get_tracer("demo-worker")


def insert_notification(conn, msg: dict) -> None:
    with tracer.start_as_current_span("INSERT notifications") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("notification.id", msg["notification_id"])
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notifications (notification_id, user_id, title, body, status) "
                "VALUES (%s, %s, %s, %s, 'delivered')",
                (msg["notification_id"], msg["user_id"], msg["title"], msg["body"]),
            )
        conn.commit()


def on_message(ch, method, properties, body):
    msg = json.loads(body)
    headers = properties.headers or {}
    with tracer.start_as_current_span("notifications.create process") as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.message.id", properties.message_id)
        span.set_attribute("messaging.rabbitmq.message.redelivered", bool(method.redelivered))
        log.info("processing notification %s", msg["notification_id"])
        insert_notification(get_conn(), msg)
        if fault_enabled() and headers.get("x-fault") == "ack_failure" and not method.redelivered:
            span.set_attribute("fault.injected", True)
            err = InjectedAckFailure("ack lost after commit")
            span.record_exception(err)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            raise err
        ch.basic_ack(delivery_tag=method.delivery_tag)`,
  'demo/db/schema.sql': `CREATE TABLE IF NOT EXISTS notifications (
    id              BIGSERIAL PRIMARY KEY,
    notification_id UUID NOT NULL,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);`,
}

export const SHA_FULL = SHA
