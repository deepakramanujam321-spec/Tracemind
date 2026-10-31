"""Orchestration: incident detection, investigations and remediations on top of the team modules."""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from tracemind.api.stores import PgInvestigationStore, PgRemediationStore
from tracemind.code import RepoRegistry, build_code_intelligence, resolve_code_ref
from tracemind.contracts import IncidentContext
from tracemind.correlation import EvidenceResolver, detect_incidents
from tracemind.investigation.graph import run_investigation
from tracemind.investigation.schemas import InvestigationDeps
from tracemind.models.factory import provider_from_env
from tracemind.remediation.engine import RemediationEngine

log = logging.getLogger("tracemind.service")


class Service:
    def __init__(self, repo: Any):
        self.repo = repo  # PostgresTelemetryRepository
        self.pool = repo.pool
        self.registry = RepoRegistry()
        self.sandbox_root = Path(os.environ.get("TRACEMIND_SANDBOX_ROOT", ".sandbox")).resolve()
        self.graph_root = Path(os.environ.get("TRACEMIND_GRAPH_ROOT", ".tracemind/graphs")).resolve()
        self.regression_test = os.environ.get("TRACEMIND_REGRESSION_TEST", "tests/test_sandbox_regression.py")

    # ---- helpers
    def q(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.pool.connection() as c:
            return list(c.execute(sql, params))

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        r = self.q(sql, params)
        return r[0] if r else None

    def context(self, incident_id: str) -> IncidentContext | None:
        r = self.one("SELECT context FROM incidents WHERE id=%s", (incident_id,))
        return IncidentContext.model_validate(r["context"]) if r else None

    def resolver(self) -> EvidenceResolver:
        ctxs = [IncidentContext.model_validate(r["context"]) for r in self.q("SELECT context FROM incidents")]
        return EvidenceResolver(self.repo, ctxs)

    def resolve_ref(self, ref: str) -> dict[str, Any] | None:
        if ref.startswith("code:"):
            try:
                r = resolve_code_ref(self.registry, ref)
            except Exception:
                return None
            return {"ref": ref, "type": "code", "record": {"repo": r.repo_id, "path": r.path, "start": r.start,
                                                           "end": r.end, "text": r.text}}
        return self.resolver().resolve(ref)

    # ---- repositories
    def register_repo(self, path: str, name: str | None = None) -> dict[str, Any]:
        info = self.registry.register(path)
        rid = info.repo_id
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO repositories (id,name,path,commit_sha) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET path=EXCLUDED.path, commit_sha=EXCLUDED.commit_sha",
                (rid, name or rid, str(info.path), info.head_sha))
        return self.one("SELECT * FROM repositories WHERE id=%s", (rid,))

    def ensure_repo_loaded(self, repo_id: str) -> None:
        try:
            self.registry.get(repo_id)
        except Exception:
            r = self.one("SELECT path FROM repositories WHERE id=%s", (repo_id,))
            if not r:
                raise KeyError(repo_id)
            self.registry.register(r["path"], repo_id=repo_id)

    # ---- incidents
    def detect(self, window_hours: int = 24) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        out = []
        for ctx in detect_incidents(self.repo, since):
            primary = ctx.trace_ids[0] if ctx.trace_ids else None
            sev = "high" if any(s.name == "redelivery_duplicate_write" for s in ctx.signals) else "medium"
            with self.pool.connection() as c:
                c.execute(
                    "INSERT INTO incidents (id,title,severity,primary_trace_id,trace_ids,services,context) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET context=EXCLUDED.context, "
                    "title=EXCLUDED.title, services=EXCLUDED.services, updated_at=now()",
                    (ctx.incident_id, ctx.title, sev, primary, ctx.trace_ids, ctx.services, Jsonb(ctx.model_dump(mode="json"))))
            out.append(self.one("SELECT * FROM incidents WHERE id=%s", (ctx.incident_id,)))
        return out

    # ---- investigation
    def start_investigation(self, incident_id: str, repo_id: str | None) -> str:
        ctx = self.context(incident_id)
        if ctx is None:
            raise KeyError(incident_id)
        if repo_id:
            self.ensure_repo_loaded(repo_id)
        inv = f"inv-{uuid.uuid4().hex[:10]}"
        with self.pool.connection() as c:
            c.execute("INSERT INTO investigations (id,incident_id,repository_id,model_provider,model_name) VALUES (%s,%s,%s,%s,%s)",
                      (inv, incident_id, repo_id, os.environ.get("MODEL_PROVIDER"), os.environ.get("MODEL_NAME")))
            c.execute("UPDATE incidents SET status='investigating', updated_at=now() WHERE id=%s", (incident_id,))
        threading.Thread(target=self._run_investigation, args=(inv, ctx, repo_id), daemon=True).start()
        return inv

    def _run_investigation(self, inv: str, ctx: IncidentContext, repo_id: str | None) -> None:
        try:
            provider = provider_from_env()
            code = build_code_intelligence(self.registry, self.graph_root, repo_id) if repo_id else None
            deps = InvestigationDeps(
                provider=provider,
                resolve=lambda ref: self.resolve_ref(ref) is not None,
                store=PgInvestigationStore(self.pool), code=code, repo_id=repo_id)
            res = run_investigation(ctx, deps, inv)
            status = "root_cause_found" if res.adjudication.outcome in ("confirmed", "suspected") else "inconclusive"
            with self.pool.connection() as c:
                c.execute("UPDATE investigations SET status='completed', finished_at=now() WHERE id=%s", (inv,))
                c.execute("UPDATE incidents SET status=%s, updated_at=now() WHERE id=%s", (status, ctx.incident_id))
        except Exception as e:  # surfaced to the UI; never silently dropped
            log.exception("investigation %s failed", inv)
            with self.pool.connection() as c:
                c.execute("UPDATE investigations SET status='failed', error=%s, finished_at=now() WHERE id=%s", (str(e), inv))
                c.execute("UPDATE incidents SET status='open' WHERE id=%s", (ctx.incident_id,))

    # ---- remediation
    def start_remediation(self, investigation_id: str) -> str:
        inv = self.one("SELECT * FROM investigations WHERE id=%s", (investigation_id,))
        if not inv:
            raise KeyError(investigation_id)
        if inv["status"] != "completed" or inv["outcome"] not in ("confirmed", "suspected"):
            raise ValueError("remediation requires a completed investigation with a supported root cause")
        if not inv["repository_id"]:
            raise ValueError("investigation has no registered repository")
        self.ensure_repo_loaded(inv["repository_id"])
        repo = self.registry.get(inv["repository_id"])
        rid = f"rem-{uuid.uuid4().hex[:10]}"
        with self.pool.connection() as c:
            c.execute("INSERT INTO remediations (id,investigation_id,repository_id,base_sha) VALUES (%s,%s,%s,%s)",
                      (rid, investigation_id, repo.repo_id, repo.head_sha))
        threading.Thread(target=self._run_remediation, args=(rid, inv, repo), daemon=True).start()
        return rid

    def _run_remediation(self, rid: str, inv: dict[str, Any], repo: Any) -> None:
        store = PgRemediationStore(self.pool)
        try:
            adj = inv["adjudication"] or {}
            hyps = self.q("SELECT * FROM hypotheses WHERE investigation_id=%s", (inv["id"],))
            root = next((h for h in hyps if h["id"].endswith(":" + (adj.get("root_cause_hypothesis_id") or ""))), None)
            refs = list(dict.fromkeys(root["supporting_refs"])) if root else []
            code_refs = [r for r in refs if r.startswith("code:")]
            from tracemind.contracts import CodeFinding
            findings = [CodeFinding(ref=r, note="cited by root-cause hypothesis") for r in code_refs]
            engine = RemediationEngine(provider_from_env(), store, self.sandbox_root,
                                       image=os.environ.get("TRACEMIND_SANDBOX_IMAGE"))
            res = engine.run(repo.path, repo.head_sha, adj.get("summary", ""), refs, findings,
                             self.regression_test, remediation_id=rid)
            with self.pool.connection() as c:
                if res.status is None:
                    c.execute("UPDATE remediations SET status='failed', error=%s WHERE id=%s",
                              (getattr(res, "error", None) or "no valid patch produced", rid))
                else:
                    c.execute("UPDATE remediations SET test_summary = COALESCE(test_summary,'{}'::jsonb) || %s WHERE id=%s",
                              (Jsonb({"tests_passed": res.tests_passed, "scenario_regression_passed": res.regression_passed,
                                      "baseline_reproduced": res.baseline_reproduced, "explanation": res.explanation}), rid))
                    if res.status == "verified":
                        c.execute("UPDATE incidents SET status='remediated' WHERE id=(SELECT incident_id FROM investigations WHERE id=%s)", (inv["id"],))
        except Exception as e:
            log.exception("remediation %s failed", rid)
            with self.pool.connection() as c:
                c.execute("UPDATE remediations SET status='failed', error=%s WHERE id=%s", (str(e), rid))
