"""Evidence guard: every ref an agent emits is validated through an injected resolver."""
from __future__ import annotations

from tracemind.contracts import Hypothesis

from .schemas import Resolver


def split_refs(refs: list[str], resolve: Resolver) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    bad: list[str] = []
    for r in dict.fromkeys(refs):  # dedupe, keep order
        try:
            good = bool(resolve(r))
        except Exception:  # a resolver crash is treated as unresolvable, never as valid
            good = False
        (ok if good else bad).append(r)
    return ok, bad


def guard_hypothesis(h: Hypothesis, resolve: Resolver) -> Hypothesis:
    sup, bad_s = split_refs(h.supporting_refs, resolve)
    con, bad_c = split_refs(h.contradicting_refs, resolve)
    h = h.model_copy(deep=True)
    h.supporting_refs, h.contradicting_refs = sup, con
    stripped = bad_s + bad_c
    if stripped:
        h.challenges.append({"by": "evidence_guard", "type": "unresolvable_refs", "stripped": stripped})
        h.missing_evidence.append(f"{len(stripped)} cited reference(s) could not be resolved and were removed")
    if not sup:
        h.missing_evidence.append("no resolvable supporting evidence")
        h.confidence = min(h.confidence, 0.2)
    return h
