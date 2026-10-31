"""Postgres-backed InvestigationStore / RemediationStore (tables defined in migrations/001_init.sql)."""
from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from tracemind.contracts import Hypothesis
from tracemind.investigation.schemas import Adjudication
from tracemind.remediation.models import CommandRun


class PgInvestigationStore:
    def __init__(self, pool: Any):
        self.pool = pool

    def save_agent_step(self, investigation_id: str, step: dict[str, Any]) -> None:
        extra = {k: v for k, v in step.items() if k not in ("agent", "status", "ts", "summary")}
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO agent_steps (investigation_id, agent, status, summary, output, finished_at) "
                "VALUES (%s,%s,%s,%s,%s, CASE WHEN %s IN ('completed','failed','skipped') THEN now() END)",
                (investigation_id, step["agent"], step["status"], step.get("summary"),
                 Jsonb(json.loads(json.dumps(extra, default=str))), step["status"]))

    def save_hypotheses(self, investigation_id: str, hypotheses: list[Hypothesis]) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM hypotheses WHERE investigation_id=%s", (investigation_id,))
            for h in hypotheses:
                c.execute(
                    "INSERT INTO hypotheses (id, investigation_id, author_agent, description, confidence, "
                    "supporting_refs, contradicting_refs, alternatives, missing_evidence, challenges, validation_status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (f"{investigation_id}:{h.id}", investigation_id, h.author_agent, h.description, h.confidence,
                     h.supporting_refs, h.contradicting_refs, h.alternatives, h.missing_evidence,
                     Jsonb(h.challenges), h.validation_status))

    def save_adjudication(self, investigation_id: str, a: Adjudication) -> None:
        # Hypothesis validation_status as judged by the adjudicator is already on the saved hypotheses.
        with self.pool.connection() as c:
            c.execute("UPDATE investigations SET adjudication=%s, outcome=%s WHERE id=%s",
                      (Jsonb(a.model_dump(mode="json")), a.outcome, investigation_id))


class PgRemediationStore:
    def __init__(self, pool: Any):
        self.pool = pool

    def record_command(self, remediation_id: str, run: CommandRun) -> None:
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO command_runs (remediation_id, phase, command, exit_code, stdout, stderr, started_at, duration_ms) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (remediation_id, run.phase, " ".join(run.command), run.exit_code, run.stdout, run.stderr,
                 run.started_at, int(run.duration_ms)))

    def set_status(self, remediation_id: str, status: str, **fields: object) -> None:
        summary = {k: v for k, v in fields.items() if k.endswith("_exit") or k == "source_refs"}
        with self.pool.connection() as c:
            c.execute(
                "UPDATE remediations SET status=%s, test_summary = COALESCE(test_summary,'{}'::jsonb) || %s WHERE id=%s",
                (status, Jsonb(summary), remediation_id))

    def save_diff(self, remediation_id: str, diff: str) -> None:
        files = sorted({ln[6:] for ln in diff.splitlines() if ln.startswith("+++ b/")})
        with self.pool.connection() as c:
            c.execute("UPDATE remediations SET diff=%s, files_changed=%s WHERE id=%s", (diff, files, remediation_id))
