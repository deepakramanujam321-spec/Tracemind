"""LLM output schemas, deps and result types for the investigation graph."""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from tracemind.contracts import (
    Certainty,
    CodeIntelligence,
    Hypothesis,
    ModelProvider,
    Validation,
)

Resolver = Callable[[str], bool]
EventSink = Callable[[dict[str, Any]], None]


class HypothesisDraft(BaseModel):
    description: str
    confidence: float = Field(ge=0, le=1)
    supporting_refs: list[str] = Field(default_factory=list)
    contradicting_refs: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class HypothesesOut(BaseModel):
    hypotheses: list[HypothesisDraft] = Field(default_factory=list)


class CodeRequest(BaseModel):
    path: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class CodeRequests(BaseModel):
    reads: list[CodeRequest] = Field(default_factory=list)


class Challenge(BaseModel):
    hypothesis_id: str
    verdict: Literal["holds", "weak", "refuted"]
    argument: str
    refs: list[str] = Field(default_factory=list)
    alternative_explanation: str | None = None


class SkepticOut(BaseModel):
    challenges: list[Challenge] = Field(default_factory=list)


class Judgement(BaseModel):
    hypothesis_id: str
    status: Validation
    rationale: str
    refs: list[str] = Field(default_factory=list)


class AdjudicationOut(BaseModel):
    judgements: list[Judgement] = Field(default_factory=list)
    root_cause_hypothesis_id: str | None = None
    outcome: Certainty = "inconclusive"
    summary: str = ""


class Adjudication(BaseModel):
    investigation_id: str
    outcome: Certainty
    root_cause_hypothesis_id: str | None = None
    summary: str
    judgements: list[Judgement]
    guard_notes: list[str] = Field(default_factory=list)


class InvestigationStore(Protocol):
    """Persistence seam; orchestrator wires Postgres (agent_steps, hypotheses, adjudication). Must be thread-safe
    (parallel nodes call it concurrently)."""

    def save_agent_step(self, investigation_id: str, step: dict[str, Any]) -> None: ...
    def save_hypotheses(self, investigation_id: str, hypotheses: list[Hypothesis]) -> None: ...
    def save_adjudication(self, investigation_id: str, adjudication: Adjudication) -> None: ...


class InMemoryInvestigationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.steps: list[dict[str, Any]] = []
        self.hypotheses: list[Hypothesis] = []
        self.adjudication: Adjudication | None = None

    def save_agent_step(self, investigation_id: str, step: dict[str, Any]) -> None:
        with self._lock:
            self.steps.append({"investigation_id": investigation_id, **step})

    def save_hypotheses(self, investigation_id: str, hypotheses: list[Hypothesis]) -> None:
        with self._lock:
            self.hypotheses = [h.model_copy(deep=True) for h in hypotheses]

    def save_adjudication(self, investigation_id: str, adjudication: Adjudication) -> None:
        with self._lock:
            self.adjudication = adjudication


@dataclass
class InvestigationDeps:
    provider: ModelProvider
    resolve: Resolver
    store: InvestigationStore
    code: CodeIntelligence | None = None
    repo_id: str | None = None
    emit: EventSink | None = None
    # Hook for Team D's remediation_engineer: called with the final result after adjudication. Not part of the graph.
    on_adjudicated: Callable[[InvestigationResult], None] | None = None
    max_code_reads: int = 5
    max_code_chars: int = 6000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class InvestigationResult(BaseModel):
    investigation_id: str
    hypotheses: list[Hypothesis]
    adjudication: Adjudication
