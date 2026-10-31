"""TraceMind HTTP API (docs/ARCHITECTURE.md §7). Sync endpoints so FastAPI runs them in a threadpool.
Response shapes follow tracemind/web/src/api/types.ts (see api/views.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tracemind.api import views
from tracemind.api.service import Service
from tracemind.code import RepoError

router = APIRouter(prefix="/api")

_INC = "SELECT i.* FROM incidents i"


def svc(request: Request) -> Service:
    return request.app.state.service


class RepoIn(BaseModel):
    path: str
    name: str | None = None


class InvestigateIn(BaseModel):
    repository_id: str | None = None


class RemediateIn(BaseModel):
    repository_id: str | None = None  # accepted for UI compatibility; the investigation's repository is used


def _inv_rows(s: Service, where: str = "", params: tuple = (), limit: int = 20) -> list[dict[str, Any]]:
    return s.q("SELECT v.*, i.title AS incident_title FROM investigations v JOIN incidents i ON i.id=v.incident_id "
               f"{where} ORDER BY v.started_at DESC LIMIT {limit}", params)


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    s = svc(request)
    return {"services": s.services_info(),
            "incidents": [views.incident_summary(r) for r in s.q(_INC + " ORDER BY detected_at DESC LIMIT 20")],
            "investigations": [views.investigation_summary(r) for r in _inv_rows(s)]}


@router.get("/services")
def services(request: Request) -> dict[str, Any]:
    s = svc(request)
    return {"services": s.services_info(), "edges": s.edges()}


@router.get("/incidents")
def incidents(request: Request) -> dict[str, Any]:
    return {"incidents": [views.incident_summary(r) for r in svc(request).q(_INC + " ORDER BY detected_at DESC")]}


@router.post("/incidents/detect")
def detect(request: Request, window_hours: int = 24) -> dict[str, Any]:
    s = svc(request)
    before = {r["id"] for r in s.q("SELECT id FROM incidents")}
    found = s.detect(window_hours)
    created = sum(1 for r in found if r["id"] not in before)
    return {"created": created, "refreshed": len(found) - created, "incidents": [views.incident_summary(r) for r in found]}


@router.get("/incidents/{incident_id}")
def incident(incident_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT * FROM incidents WHERE id=%s", (incident_id,))
    if not row:
        raise HTTPException(404, "incident not found")
    return {**views.incident_summary(row), "context": row["context"],
            "investigations": [views.investigation_summary(r) for r in _inv_rows(s, "WHERE v.incident_id=%s", (incident_id,), 50)]}


@router.get("/incidents/{incident_id}/traces/{trace_id}")
def trace(incident_id: str, trace_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    spans = s.repo.get_trace(trace_id)
    if not spans:
        raise HTTPException(404, "trace not found")
    return {"trace_id": trace_id, "spans": [x.model_dump(mode="json") for x in spans],
            "logs": [x.model_dump(mode="json") for x in s.repo.get_logs_for_trace(trace_id)]}


@router.get("/evidence/{ref:path}")
def evidence(ref: str, request: Request) -> dict[str, Any]:
    kind = ref.split(":", 1)[0]
    r = svc(request).resolve_ref(ref)
    if r is None:
        return {"ref": ref, "kind": kind if kind in ("span", "event", "log", "code", "sig") else "span", "resolved": False,
                "title": "Unresolved reference", "record": None, "excerpt": None,
                "error": "reference does not resolve to stored telemetry or source code"}
    if r["type"] == "code":
        c = r["record"]
        return {"ref": ref, "kind": "code", "resolved": True, "title": f'{c["path"]}:{c["start"]}-{c["end"]}',
                "record": None, "error": None,
                "excerpt": {"repo_id": c["repo"] if "repo" in c else c.get("repo_id"), "path": c["path"], "start_line": c["start"],
                            "end_line": c["end"], "lines": c["text"].splitlines(), "sha": None}}
    rec = r["record"]
    title = {"span": lambda: f'{rec.get("service_name")} · {rec.get("name")}', "event": lambda: f'event {rec.get("name")}',
             "log": lambda: f'log · {rec.get("service_name")}', "signal": lambda: rec.get("name", "signal")}[r["type"]]()
    return {"ref": ref, "kind": "sig" if r["type"] == "signal" else r["type"], "resolved": True, "title": title,
            "record": rec, "excerpt": None, "error": None}


@router.post("/repositories", status_code=201)
def register_repo(body: RepoIn, request: Request) -> dict[str, Any]:
    try:
        return svc(request).register_repo(body.path, body.name)
    except RepoError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/repositories")
def repositories(request: Request) -> list[dict[str, Any]]:
    return svc(request).q("SELECT * FROM repositories ORDER BY registered_at DESC")


@router.post("/incidents/{incident_id}/investigations", status_code=202)
def start_investigation(incident_id: str, request: Request, body: InvestigateIn | None = None) -> dict[str, str]:
    s = svc(request)
    repo_id = body.repository_id if body else None
    if repo_id is None:  # default to the most recently registered repository
        r = s.one("SELECT id FROM repositories ORDER BY registered_at DESC LIMIT 1")
        repo_id = r["id"] if r else None
    try:
        return {"investigation_id": s.start_investigation(incident_id, repo_id)}
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}") from e


@router.get("/investigations/{investigation_id}")
def investigation(investigation_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    rows = _inv_rows(s, "WHERE v.id=%s", (investigation_id,), 1)
    if not rows:
        raise HTTPException(404, "investigation not found")
    row = rows[0]
    repo = s.one("SELECT graph_status FROM repositories WHERE id=%s", (row["repository_id"],)) if row["repository_id"] else None
    return views.investigation(
        row,
        s.q("SELECT agent,status,summary,output,started_at,finished_at FROM agent_steps WHERE investigation_id=%s ORDER BY id", (investigation_id,)),
        s.q("SELECT * FROM hypotheses WHERE investigation_id=%s ORDER BY id", (investigation_id,)),
        s.q("SELECT id,status FROM remediations WHERE investigation_id=%s ORDER BY created_at DESC", (investigation_id,)),
        repo["graph_status"] if repo else None)


@router.post("/investigations/{investigation_id}/remediations", status_code=202)
def start_remediation(investigation_id: str, request: Request, body: RemediateIn | None = None) -> dict[str, str]:
    try:
        return {"remediation_id": svc(request).start_remediation(investigation_id)}
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


def _remediation(s: Service, rid: str) -> dict[str, Any]:
    row = s.one("SELECT r.*, v.incident_id FROM remediations r JOIN investigations v ON v.id=r.investigation_id WHERE r.id=%s", (rid,))
    if not row:
        raise HTTPException(404, "remediation not found")
    return views.remediation(row, s.q("SELECT * FROM command_runs WHERE remediation_id=%s ORDER BY id", (rid,)))


@router.get("/remediations/{remediation_id}")
def remediation(remediation_id: str, request: Request) -> dict[str, Any]:
    return _remediation(svc(request), remediation_id)


@router.post("/remediations/{remediation_id}/approve")
def approve(remediation_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT status FROM remediations WHERE id=%s", (remediation_id,))
    if not row:
        raise HTTPException(404, "remediation not found")
    if row["status"] != "verified":
        raise HTTPException(409, "only a verified remediation can be approved")
    s.q("UPDATE remediations SET approved_at=now() WHERE id=%s RETURNING id", (remediation_id,))
    return _remediation(s, remediation_id)
