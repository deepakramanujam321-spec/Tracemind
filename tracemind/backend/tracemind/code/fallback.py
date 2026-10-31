"""FALLBACK code intelligence (backend='fallback'): git-tracked file grep + Python AST. No Graphify."""
from __future__ import annotations

import re
from typing import Literal

from ..contracts import CodeFinding
from ._common import python_spans, tokens
from .refs import make_code_ref
from .repos import RepoRegistry

_MAX_BYTES = 512_000


class FallbackCodeIntelligence:
    backend: Literal["graphify", "fallback"] = "fallback"

    def __init__(self, registry: RepoRegistry) -> None:
        self.registry = registry

    def _files(self, repo_id: str) -> list[tuple[str, str]]:
        info = self.registry.get(repo_id)
        out = []
        for rel in self.registry.tracked_files(repo_id):
            p = info.path / rel
            if p.is_symlink() or not p.is_file() or p.stat().st_size > _MAX_BYTES:
                continue
            try:
                out.append((rel, p.read_text(encoding="utf-8")))
            except UnicodeDecodeError:
                continue
        return out

    def find_candidates(self, repo_id: str, query: str, limit: int = 10) -> list[CodeFinding]:
        toks = tokens(query)
        if not toks:
            return []
        scored: list[tuple[float, CodeFinding]] = []
        for rel, text in self._files(repo_id):
            lines = text.splitlines()
            spans = python_spans(text) if rel.endswith(".py") else {}
            if spans:
                for start, (end, name) in spans.items():
                    body = "\n".join(lines[start - 1 : end]).lower()
                    hits = sum(1 for t in toks if t in body)
                    name_hits = sum(1 for t in toks if t in name.lower())
                    if hits:
                        score = hits + 3 * name_hits + (1 if "test" in rel else 0) * 0.0
                        scored.append((score, CodeFinding(
                            ref=make_code_ref(repo_id, rel, start, end), symbol=name,
                            note=f"[fallback AST] def/class {name} matches {hits}/{len(toks)} query terms")))
            else:
                for i, line in enumerate(lines, 1):
                    hits = sum(1 for t in toks if t in line.lower())
                    if hits:
                        scored.append((hits * 0.5, CodeFinding(
                            ref=make_code_ref(repo_id, rel, i, i), symbol=None,
                            note=f"[fallback grep] line matches {hits} query terms: {line.strip()[:120]}")))
        scored.sort(key=lambda s: -s[0])
        return [f for _, f in scored[:limit]]

    def read_source(self, repo_id: str, path: str, start: int, end: int) -> str:
        return self.registry.read_source(repo_id, path, start, end)

    def related(self, repo_id: str, symbol: str) -> list[CodeFinding]:
        name = symbol.rstrip("()").split(".")[-1]
        files = self._files(repo_id)
        defs: dict[str, tuple[str, int, int]] = {}
        for rel, text in files:
            if rel.endswith(".py"):
                for s, (e, n) in python_spans(text).items():
                    defs.setdefault(n, (rel, s, e))
        out: list[CodeFinding] = []
        call = re.compile(rf"\b{re.escape(name)}\s*\(")
        for rel, text in files:
            if not rel.endswith(".py"):
                continue
            for s, (e, n) in python_spans(text).items():
                if n == name:
                    # callees: other known defs called inside body
                    body = "\n".join(text.splitlines()[s - 1 : e])
                    for dn, (drel, ds, de) in defs.items():
                        if dn != name and re.search(rf"\b{re.escape(dn)}\s*\(", body):
                            out.append(CodeFinding(ref=make_code_ref(repo_id, drel, ds, de), symbol=dn,
                                                   note=f"[fallback] {name} calls {dn}"))
                elif call.search("\n".join(text.splitlines()[s - 1 : e])):
                    out.append(CodeFinding(ref=make_code_ref(repo_id, rel, s, e), symbol=n,
                                           note=f"[fallback] {n} calls {name}"))
        return out
