"""Agent node implementations (pure functions of state + deps)."""
from __future__ import annotations

import re
import time
from typing import Any

from tracemind.contracts import Hypothesis, Message

from . import prompts as P
from .guard import guard_hypothesis, split_refs
from .schemas import (
    Adjudication,
    AdjudicationOut,
    CodeRequests,
    HypothesesOut,
    InvestigationDeps,
    Judgement,
    SkepticOut,
)

_CODE_REF = re.compile(r"^code:(?P<repo>[^:]+):(?P<path>.+):(?P<a>\d+)-(?P<b>\d+)$")


def _step(deps: InvestigationDeps, inv_id: str, agent: str, status: str, **extra: Any) -> None:
    step = {"agent": agent, "status": status, "ts": time.time(), **extra}
    deps.store.save_agent_step(inv_id, step)
    if deps.emit:
        with deps._lock:
            deps.emit({"type": "agent_step", "investigation_id": inv_id, **step})


def _to_hypotheses(out: HypothesesOut, agent: str, prefix: str) -> list[Hypothesis]:
    return [
        Hypothesis(id=f"{prefix}{i}", author_agent=agent, description=d.description, confidence=d.confidence,
                   supporting_refs=d.supporting_refs, contradicting_refs=d.contradicting_refs,
                   alternatives=d.alternatives, missing_evidence=d.missing_evidence)
        for i, d in enumerate(out.hypotheses, 1)
    ]


def _independent(deps, inv_id, agent, prefix, messages) -> list[Hypothesis]:
    _step(deps, inv_id, agent, "started")
    try:
        out = deps.provider.generate_structured(messages, HypothesesOut)
        hyps = [guard_hypothesis(h, deps.resolve) for h in _to_hypotheses(out, agent, prefix)]
    except Exception as e:  # model failure must not crash the graph; adjudicator will see no evidence
        _step(deps, inv_id, agent, "failed", error=str(e)[:500])
        return []
    _step(deps, inv_id, agent, "completed", hypothesis_ids=[h.id for h in hyps])
    return hyps


def trace_investigator(state: dict, deps: InvestigationDeps) -> dict:
    ctx = state["context"]
    msgs = [
        P.system("trace_investigator", "From telemetry only (spans, events, logs, signals), form independent causal "
                 "hypotheses. Do not speculate about source code. Follow causal order: origin, transformation, impact."),
        Message(role="user", content=P.data_block("incident_context", P.context_text(ctx))
                + "\nReturn JSON {hypotheses:[{description, confidence(0-1, an estimate not a probability), "
                  "supporting_refs, contradicting_refs, alternatives, missing_evidence}]}."),
    ]
    return {"hypotheses": _independent(deps, state["investigation_id"], "trace_investigator", "T", msgs)}


def code_analyst(state: dict, deps: InvestigationDeps) -> dict:
    inv, ctx = state["investigation_id"], state["context"]
    agent = "code_analyst"
    if deps.code is None or not deps.repo_id:
        _step(deps, inv, agent, "skipped", reason="no code intelligence / repository configured")
        return {"hypotheses": [], "notes": ["code_analyst skipped: no repository"]}
    _step(deps, inv, agent, "started", backend=deps.code.backend)
    try:
        query = " ".join([ctx.title, *[s.name for s in ctx.signals]])
        cands = deps.code.find_candidates(deps.repo_id, query, limit=10)
        cand_txt = "\n".join(f"{c.ref} symbol={c.symbol} {c.note}" for c in cands)
        pick = deps.provider.generate_structured([
            P.system(agent, "Choose which source ranges to read to test code-level explanations. Do not claim anything "
                     "about code yet."),
            Message(role="user", content=P.data_block("incident_context", P.context_text(ctx))
                    + "\n" + P.data_block("code_candidates", cand_txt)
                    + f"\nReturn JSON {{reads:[{{path,start,end}}]}}, at most {deps.max_code_reads}."),
        ], CodeRequests)
        sources: list[tuple[str, str]] = []  # (ref, text) actually read
        for r in pick.reads[: deps.max_code_reads]:
            if r.end < r.start:
                continue
            text = deps.code.read_source(deps.repo_id, r.path, r.start, r.end)
            ref = f"code:{deps.repo_id}:{r.path}:{r.start}-{r.end}"
            if text:
                sources.append((ref, text[: deps.max_code_chars]))
        src_txt = "\n\n".join(f"REF {ref}\n{text}" for ref, text in sources) or "(no source could be read)"
        msgs = [
            P.system(agent, "Form independent hypotheses. Code-level claims are only allowed about source shown to "
                     "you below and must cite its code: ref. Telemetry-level claims cite telemetry refs. "
                     "In supporting_refs/contradicting_refs copy refs VERBATIM from the REF lines or the incident "
                     "context: a code ref always starts with 'code:' and ends with a line range (code:<repo>:<path>:"
                     "<start>-<end>). Never shorten, reformat or invent refs; unresolvable refs are discarded."),
            Message(role="user", content=P.data_block("incident_context", P.context_text(ctx))
                    + "\n" + P.data_block("source_code_read", src_txt)
                    + "\nValid code refs (copy exactly): " + (", ".join(ref for ref, _ in sources) or "none")
                    + "\nReturn JSON {hypotheses:[{description, confidence, supporting_refs, contradicting_refs, "
                      "alternatives, missing_evidence}]}."),
        ]
        out = deps.provider.generate_structured(msgs, HypothesesOut)
        read_refs = [ref for ref, _ in sources]
        hyps = []
        for h in _to_hypotheses(out, agent, "C"):
            # code refs must be (inside) a range that was actually read
            for fld in ("supporting_refs", "contradicting_refs"):
                kept = [r for r in getattr(h, fld) if not r.startswith("code:") or _covered(r, read_refs)]
                if len(kept) != len(getattr(h, fld)):
                    h.challenges.append({"by": "evidence_guard", "type": "code_ref_not_read",
                                         "stripped": [r for r in getattr(h, fld) if r not in kept]})
                setattr(h, fld, kept)
            hyps.append(guard_hypothesis(h, deps.resolve))
    except Exception as e:
        _step(deps, inv, agent, "failed", error=str(e)[:500])
        return {"hypotheses": []}
    _step(deps, inv, agent, "completed", hypothesis_ids=[h.id for h in hyps], code_reads=[r for r, _ in sources])
    return {"hypotheses": hyps}


def _covered(ref: str, read_refs: list[str]) -> bool:
    m = _CODE_REF.match(ref)
    if not m:
        return False
    for rr in read_refs:
        n = _CODE_REF.match(rr)
        if n and n["repo"] == m["repo"] and n["path"] == m["path"] and int(n["a"]) <= int(m["a"]) \
                and int(m["b"]) <= int(n["b"]):
            return True
    return False


def skeptic(state: dict, deps: InvestigationDeps) -> dict:
    inv, hyps = state["investigation_id"], state["hypotheses"]
    _step(deps, inv, "skeptic", "started")
    if not hyps:
        _step(deps, inv, "skeptic", "completed", note="no hypotheses to challenge")
        return {"reviewed": []}
    msgs = [
        P.system("skeptic", "Challenge EVERY hypothesis. Look for contradicting evidence, unsupported leaps, "
                 "alternative explanations and missing evidence. verdict: holds | weak | refuted."),
        Message(role="user", content=P.data_block("incident_context", P.context_text(state["context"]))
                + "\nHYPOTHESES (model-authored, may be wrong):\n" + P.hypotheses_text(hyps)
                + "\nReturn JSON {challenges:[{hypothesis_id, verdict, argument, refs, alternative_explanation}]} "
                  "with one entry per hypothesis."),
    ]
    try:
        out = deps.provider.generate_structured(msgs, SkepticOut)
    except Exception as e:
        _step(deps, inv, "skeptic", "failed", error=str(e)[:500])
        out = SkepticOut()
    by_id = {h.id: h.model_copy(deep=True) for h in hyps}
    for c in out.challenges:
        h = by_id.get(c.hypothesis_id)
        if h is None:
            continue
        ok, bad = split_refs(c.refs, deps.resolve)
        h.challenges.append({"by": "skeptic", "verdict": c.verdict, "argument": c.argument, "refs": ok,
                             "stripped_refs": bad, "alternative_explanation": c.alternative_explanation})
        if c.alternative_explanation:
            h.alternatives.append(c.alternative_explanation)
    for h in by_id.values():
        if not any(ch.get("by") == "skeptic" for ch in h.challenges):
            h.challenges.append({"by": "skeptic", "verdict": "unchallenged",
                                 "argument": "skeptic produced no challenge for this hypothesis"})
    result = list(by_id.values())
    _step(deps, inv, "skeptic", "completed", challenged=len(out.challenges))
    return {"reviewed": result}


def adjudicator(state: dict, deps: InvestigationDeps) -> dict:
    inv, hyps = state["investigation_id"], state["reviewed"]
    _step(deps, inv, "adjudicator", "started")
    notes: list[str] = list(state.get("notes", []))
    out = AdjudicationOut()
    if hyps:
        msgs = [
            P.system("adjudicator", "Decide each hypothesis: supported | rejected | inconclusive, on evidence only. "
                     "'supported' requires resolved supporting refs and no unanswered skeptic refutation. No voting. "
                     "outcome: confirmed | suspected | inconclusive."),
            Message(role="user", content=P.data_block("incident_context", P.context_text(state["context"]))
                    + "\nHYPOTHESES WITH CHALLENGES:\n" + P.hypotheses_text(hyps)
                    + "\nReturn JSON {judgements:[{hypothesis_id,status,rationale,refs}], "
                      "root_cause_hypothesis_id, outcome, summary}."),
        ]
        try:
            out = deps.provider.generate_structured(msgs, AdjudicationOut)
        except Exception as e:
            _step(deps, inv, "adjudicator", "failed", error=str(e)[:500])
            notes.append(f"adjudicator model failure: {e}")
    judged = {j.hypothesis_id: j for j in out.judgements}
    final: list[Judgement] = []
    updated: list[Hypothesis] = []
    for h in hyps:
        j = judged.get(h.id) or Judgement(hypothesis_id=h.id, status="inconclusive",
                                          rationale="adjudicator gave no judgement")
        j = j.model_copy(update={"refs": split_refs(j.refs, deps.resolve)[0]})
        if j.status == "supported" and not h.supporting_refs:
            notes.append(f"{h.id}: downgraded supported->inconclusive (no resolved supporting evidence)")
            j = j.model_copy(update={"status": "inconclusive",
                                     "rationale": "Downgraded by evidence guard: " + j.rationale})
        h2 = h.model_copy(update={"validation_status": j.status})
        updated.append(h2)
        final.append(j)
    supported = [j for j in final if j.status == "supported"]
    root = out.root_cause_hypothesis_id
    if not supported:
        root, outcome = None, "inconclusive"
    else:
        if root not in {j.hypothesis_id for j in supported}:
            root = max(supported, key=lambda j: next(h.confidence for h in updated if h.id == j.hypothesis_id)
                       ).hypothesis_id
        rh = next(h for h in updated if h.id == root)
        outcome = out.outcome
        if outcome == "confirmed" and len(rh.supporting_refs) < 2:
            outcome = "suspected"
            notes.append("confirmed->suspected: fewer than 2 resolved supporting refs")
        if outcome == "inconclusive":
            outcome = "suspected"
    adj = Adjudication(investigation_id=inv, outcome=outcome, root_cause_hypothesis_id=root,
                       summary=out.summary or ("No hypothesis is supported by resolved evidence." if not supported
                                               else ""),
                       judgements=final, guard_notes=notes)
    _step(deps, inv, "adjudicator", "completed", outcome=outcome)
    return {"final": updated, "adjudication": adj}
