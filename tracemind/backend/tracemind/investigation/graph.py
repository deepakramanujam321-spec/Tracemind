"""LangGraph wiring: (trace_investigator || code_analyst) -> skeptic -> adjudicator."""
from __future__ import annotations

import asyncio
import operator
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tracemind.contracts import Hypothesis, IncidentContext

from . import agents
from .schemas import Adjudication, InvestigationDeps, InvestigationResult


def build_graph(deps: InvestigationDeps):
    class S(TypedDict, total=False):
        investigation_id: str
        context: IncidentContext
        hypotheses: Annotated[list[Hypothesis], operator.add]  # fan-in of the two independent agents
        notes: Annotated[list[str], operator.add]
        reviewed: list[Hypothesis]
        final: list[Hypothesis]
        adjudication: Adjudication

    g = StateGraph(S)
    g.add_node("trace_investigator", lambda s: agents.trace_investigator(s, deps))
    g.add_node("code_analyst", lambda s: agents.code_analyst(s, deps))
    g.add_node("skeptic", lambda s: agents.skeptic(s, deps))
    g.add_node("adjudicator", lambda s: agents.adjudicator(s, deps))
    g.add_edge(START, "trace_investigator")
    g.add_edge(START, "code_analyst")  # parallel fan-out: neither sees the other's output
    g.add_edge(["trace_investigator", "code_analyst"], "skeptic")
    g.add_edge("skeptic", "adjudicator")
    g.add_edge("adjudicator", END)
    return g.compile()


def run_investigation(context: IncidentContext, deps: InvestigationDeps,
                      investigation_id: str | None = None) -> InvestigationResult:
    inv = investigation_id or f"inv-{uuid.uuid4().hex[:12]}"
    final = build_graph(deps).invoke({"investigation_id": inv, "context": context, "hypotheses": [], "notes": []})
    result = InvestigationResult(investigation_id=inv, hypotheses=final["final"],
                                 adjudication=final["adjudication"])
    deps.store.save_hypotheses(inv, result.hypotheses)
    deps.store.save_adjudication(inv, result.adjudication)
    if deps.emit:
        deps.emit({"type": "completed", "investigation_id": inv, "outcome": result.adjudication.outcome})
    if deps.on_adjudicated:  # hook for the remediation_engineer (Team D)
        deps.on_adjudicated(result)
    return result


async def stream_investigation(context: IncidentContext, deps: InvestigationDeps,
                               investigation_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Async wrapper: runs the graph in a worker thread and yields step events as they happen.
    Final event has type 'completed' (with 'result') or 'failed'."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    inv = investigation_id or f"inv-{uuid.uuid4().hex[:12]}"
    upstream = deps.emit

    def sink(ev: dict[str, Any]) -> None:
        if upstream:
            upstream(ev)
        if ev.get("type") != "completed":
            loop.call_soon_threadsafe(q.put_nowait, ev)

    local = InvestigationDeps(**{**deps.__dict__, "emit": sink})

    def work() -> None:
        try:
            res = run_investigation(context, local, inv)
            loop.call_soon_threadsafe(q.put_nowait, {"type": "completed", "investigation_id": inv, "result": res})
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "failed", "investigation_id": inv, "error": str(e)})
        loop.call_soon_threadsafe(q.put_nowait, None)

    task = asyncio.get_running_loop().run_in_executor(None, work)
    while (ev := await q.get()) is not None:
        yield ev
    await task
