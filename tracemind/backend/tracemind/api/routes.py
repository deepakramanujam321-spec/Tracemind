"""TraceMind HTTP API (docs/ARCHITECTURE.md §7). Endpoints are sync so FastAPI runs them in a threadpool."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tracemind.api.service import Service
from tracemind.code import RepoError

router = APIRouter(prefix="/api")


def svc(request: Request) -> Service:
    return request.app.state.service


class RepoIn(BaseModel):
    path: str
    name: str | None = None


class InvestigateIn(BaseModel):
    repository_id: str | None = None


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    s = svc(request)
    return {
        "services": s.repo.list_services(),
        "edges": sorted({e for r in s.q("SELECT context FROM incidents") for e in map(tuple, r["context"].get("edges", []))}),
        "incidents": s.q("SELECT id,title,status,severity,services,detected_at,updated_at FROM incidents ORDER BY detected_at DESC LIMIT 20"),
        "investigations": s.q("SELECT id,incident_id,status,outcome,started_at,finished_at FROM investigations ORDER BY started_at DESC LIMIT 20"),
    }


@router.get("/services")
def services(request: Request) -> list[dict[str, Any]]:
    return svc(request).repo.list_services()


@router.get("/incidents")
def incidents(request: Request) -> list[dict[str, Any]]:
    return svc(request).q("SELECT id,title,status,severity,primary_trace_id,trace_ids,services,detected_at,updated_at FROM incidents ORDER BY detected_at DESC")


@router.post("/incidents/detect")
def detect(request: Request, window_hours: int = 24) -> list[dict[str, Any]]:
    return svc(request).detect(window_hours)


@router.get("/incidents/{incident_id}")
def incident(incident_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT * FROM incidents WHERE id=%s", (incident_id,))
    if not row:
        raise HTTPException(404, "incident not found")
    row["investigations"] = s.q("SELECT id,status,outcome,started_at,finished_at FROM investigations WHERE incident_id=%s ORDER BY started_at DESC", (incident_id,))
    return row


@router.get("/incidents/{incident_id}/traces/{trace_id}")
def trace(incident_id: str, trace_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    spans = s.repo.get_trace(trace_id)
    if not spans:
        raise HTTPException(404, "trace not found")
    return {"incident_id": incident_id, "trace_id": trace_id,
            "spans": [x.model_dump(mode="json") for x in spans],
            "logs": [x.model_dump(mode="json") for x in s.repo.get_logs_for_trace(trace_id)]}


@router.get("/evidence/{ref:path}")
def evidence(ref: str, request: Request) -> dict[str, Any]:
    r = svc(request).resolve_ref(ref)
    if r is None:
        raise HTTPException(404, "evidence reference does not resolve")
    return r


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
def start_investigation(incident_id: str, body: InvestigateIn, request: Request) -> dict[str, str]:
    try:
        return {"investigation_id": svc(request).start_investigation(incident_id, body.repository_id)}
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}") from e


@router.get("/investigations/{investigation_id}")
def investigation(investigation_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT * FROM investigations WHERE id=%s", (investigation_id,))
    if not row:
        raise HTTPException(404, "investigation not found")
    row["steps"] = s.q("SELECT agent,status,summary,output,started_at,finished_at FROM agent_steps WHERE investigation_id=%s ORDER BY id", (investigation_id,))
    row["hypotheses"] = s.q("SELECT * FROM hypotheses WHERE investigation_id=%s ORDER BY id", (investigation_id,))
    row["remediations"] = s.q("SELECT id,status,created_at FROM remediations WHERE investigation_id=%s ORDER BY created_at DESC", (investigation_id,))
    return row


@router.post("/investigations/{investigation_id}/remediations", status_code=202)
def start_remediation(investigation_id: str, request: Request) -> dict[str, str]:
    try:
        return {"remediation_id": svc(request).start_remediation(investigation_id)}
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/remediations/{remediation_id}")
def remediation(remediation_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT * FROM remediations WHERE id=%s", (remediation_id,))
    if not row:
        raise HTTPException(404, "remediation not found")
    row["command_runs"] = s.q("SELECT command,exit_code,stdout,stderr,started_at,duration_ms FROM command_runs WHERE remediation_id=%s ORDER BY id", (remediation_id,))
    return row


@router.post("/remediations/{remediation_id}/approve")
def approve(remediation_id: str, request: Request) -> dict[str, Any]:
    s = svc(request)
    row = s.one("SELECT status FROM remediations WHERE id=%s", (remediation_id,))
    if not row:
        raise HTTPException(404, "remediation not found")
    if row["status"] != "verified":
        raise HTTPException(409, "only a verified remediation can be approved")
    s.q("UPDATE remediations SET approved_at=now() WHERE id=%s RETURNING id", (remediation_id,))
    return s.one("SELECT id,status,approved_at FROM remediations WHERE id=%s", (remediation_id,))
