"""Row -> API shape adapters. The response shapes are what tracemind/web/src/api/types.ts consumes."""
from __future__ import annotations

from typing import Any

ROLES = {"trace_investigator": "Telemetry analysis", "code_analyst": "Code analysis", "skeptic": "Skeptic review",
         "adjudicator": "Adjudication", "remediation_engineer": "Remediation"}
_TERMINAL = {"completed", "failed", "skipped"}


def incident_status(s: str) -> str:
    return {"remediated": "resolved", "investigating": "investigating"}.get(s, "open")


def incident_summary(r: dict[str, Any]) -> dict[str, Any]:
    ctx = r.get("context") or {}
    return {"id": r["id"], "title": r["title"], "status": incident_status(r["status"]), "severity": r["severity"],
            "services": r["services"], "trace_ids": r["trace_ids"], "signal_count": len(ctx.get("signals", [])),
            "first_seen": r["detected_at"], "last_seen": r["updated_at"]}


def investigation_summary(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "incident_id": r["incident_id"], "incident_title": r.get("incident_title") or "",
            "status": r["status"], "certainty": r.get("outcome"), "started_at": r["started_at"],
            "finished_at": r["finished_at"]}


def _short(inv: str, hid: str) -> str:
    return hid.removeprefix(f"{inv}:")


def steps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """agent_steps holds one row per event (started/completed/...); collapse to one entry per agent."""
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        out = r.get("output") or {}
        cur = by.setdefault(r["agent"], {"id": r["agent"], "agent": r["agent"], "role": ROLES.get(r["agent"], r["agent"]),
                                         "status": "running", "started_at": r["started_at"], "finished_at": None,
                                         "summary": None, "evidence_refs": [], "error": None})
        st = "running" if r["status"] == "started" else r["status"]
        cur["status"] = st
        if st in _TERMINAL:
            cur["finished_at"] = r["finished_at"] or r["started_at"]
        cur["error"] = out.get("error") or cur["error"]
        hyps = out.get("hypothesis_ids")
        cur["summary"] = (out.get("reason") or out.get("note") or r.get("summary")
                          or (f"Proposed {len(hyps)} hypothesis(es): {', '.join(hyps)}" if hyps else cur["summary"]))
        cur["evidence_refs"] = out.get("code_reads") or cur["evidence_refs"]
    return list(by.values())


def hypothesis(inv: str, h: dict[str, Any]) -> dict[str, Any]:
    ch = []
    for c in h["challenges"]:
        v = c.get("verdict")
        ch.append({**c, "by": c.get("by", "skeptic"), "challenge": c.get("argument") or c.get("type") or "",
                   "response": c.get("alternative_explanation"),
                   "outcome": {"refuted": "upheld", "weak": "unresolved", "holds": "withdrawn"}.get(v, "unresolved")})
    return {"id": _short(inv, h["id"]), "author_agent": h["author_agent"], "description": h["description"],
            "confidence": h["confidence"] or 0, "supporting_refs": h["supporting_refs"],
            "contradicting_refs": h["contradicting_refs"], "alternatives": h["alternatives"],
            "missing_evidence": h["missing_evidence"], "challenges": ch, "validation_status": h["validation_status"]}


def adjudication(a: dict[str, Any] | None, hyps: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not a:
        return None
    win = next((h for h in hyps if h["id"] == a.get("root_cause_hypothesis_id")), None)
    return {"certainty": a["outcome"], "winning_hypothesis_id": a.get("root_cause_hypothesis_id"),
            "root_cause": win["description"] if win else "No root cause could be established from the evidence.",
            "rationale": a.get("summary", ""),
            "rejected_hypothesis_ids": [j["hypothesis_id"] for j in a.get("judgements", []) if j["status"] == "rejected"],
            "evidence_refs": win["supporting_refs"] if win else [],
            "limitations": a.get("guard_notes", []), "rejected_refs": []}


def investigation(r: dict[str, Any], step_rows, hyp_rows, rem_rows, backend: str | None) -> dict[str, Any]:
    hyps = [hypothesis(r["id"], h) for h in hyp_rows]
    return {"id": r["id"], "incident_id": r["incident_id"], "incident_title": r.get("incident_title") or "",
            "status": r["status"], "started_at": r["started_at"], "finished_at": r["finished_at"], "error": r["error"],
            "model": "/".join(x for x in (r["model_provider"], r["model_name"]) if x) or None,
            "code_backend": backend if backend in ("graphify", "fallback") else None,
            "steps": steps(step_rows), "hypotheses": hyps, "adjudication": adjudication(r["adjudication"], hyps),
            "remediations": [{"id": x["id"], "status": _rem_status(x["status"])} for x in rem_rows]}


def _rem_status(s: str) -> str:
    return "running" if s == "pending" else s


_PHASE = {"baseline_test": "baseline", "test": "after_patch", "regression_test": "after_patch"}


def remediation(r: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    ts = r.get("test_summary") or {}
    results = []
    for c in runs:
        if c["phase"] in _PHASE:
            ok = c["exit_code"] == 0
            name = "full test suite" if c["phase"] == "test" else c["command"].split()[-1]
            results.append({"name": ("regression: " if c["phase"] == "regression_test" else "") + name,
                            "outcome": "passed" if ok else ("error" if c["exit_code"] is None else "failed"),
                            "phase": _PHASE[c["phase"]], "detail": (c["stdout"] or c["stderr"] or "")[-400:] or None})
    return {"id": r["id"], "investigation_id": r["investigation_id"], "incident_id": r.get("incident_id") or "",
            "status": _rem_status(r["status"]), "repository_id": r["repository_id"], "base_sha": r["base_sha"],
            "source_refs": ts.get("source_refs", []), "summary": ts.get("explanation"), "diff": r["diff"],
            "command_runs": [{"id": str(c["id"]), "command": c["command"], "phase": c["phase"] or "",
                              "exit_code": c["exit_code"], "duration_ms": c["duration_ms"], "stdout": c["stdout"] or "",
                              "stderr": c["stderr"] or "", "started_at": c["started_at"]} for c in runs],
            "test_results": results, "error": r["error"], "approved": r["approved_at"] is not None,
            "approved_by": "human reviewer" if r["approved_at"] else None, "approved_at": r["approved_at"],
            "created_at": r["created_at"]}
