"""Graphify-backed code intelligence (backend='graphify').

Graph is built with `graphify extract <repo> --code-only --out <graph_root>/<repo_id>` (AST only, no LLM, no API
key) so `graphify-out/` is written OUTSIDE the source repo, which stays clean. (`graphify update` always writes
`<repo>/graphify-out`, which would dirty the repo.) Queries use the real CLI (`explain`, `affected`) plus direct
parsing of graph.json for node locations. Graphify only records a symbol's START line (`source_location: "L2"`);
end lines are derived from the Python AST (or a bounded window for other languages).
Output is a discovery aid: every returned ref is validated against real file lines before being returned.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from ..contracts import CodeFinding
from ._common import end_line_for, tokens
from .refs import make_code_ref
from .repos import RepoError, RepoRegistry, safe_join


class GraphifyUnavailable(RuntimeError):
    """Graphify missing, failed, or produced no usable graph. Callers should use the fallback."""


_CONN = re.compile(r"^\s+(<--|-->)\s+(.+?)\s+\[(\w+)\]")


class GraphifyCodeIntelligence:
    backend: Literal["graphify", "fallback"] = "graphify"

    def __init__(self, registry: RepoRegistry, graph_root: Path, cli: str | None = None, timeout: float = 120) -> None:
        self.registry = registry
        self.graph_root = Path(graph_root)
        self.cli = cli or shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
        self.timeout = timeout
        self._graphs: dict[str, dict[str, Any]] = {}

    # ---- graph lifecycle
    def graph_path(self, repo_id: str) -> Path:
        return self.graph_root / repo_id / "graphify-out" / "graph.json"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run([self.cli, *args], capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise GraphifyUnavailable(f"graphify invocation failed: {e}") from e

    def build(self, repo_id: str) -> Path:
        info = self.registry.get(repo_id)
        out_dir = self.graph_root / repo_id
        out_dir.mkdir(parents=True, exist_ok=True)
        r = self._run("extract", str(info.path), "--code-only", "--out", str(out_dir))
        gp = self.graph_path(repo_id)
        if r.returncode != 0 or not gp.is_file():
            raise GraphifyUnavailable(f"graphify extract failed rc={r.returncode}: {(r.stderr or r.stdout)[-500:]}")
        self._graphs.pop(repo_id, None)
        return gp

    def _graph(self, repo_id: str) -> dict[str, Any]:
        if repo_id not in self._graphs:
            gp = self.graph_path(repo_id)
            if not gp.is_file():
                gp = self.build(repo_id)
            try:
                self._graphs[repo_id] = json.loads(gp.read_text())
            except (OSError, json.JSONDecodeError) as e:
                raise GraphifyUnavailable(f"unreadable graph.json: {e}") from e
        return self._graphs[repo_id]

    # ---- helpers
    def _finding(self, repo_id: str, node: dict[str, Any], note: str) -> CodeFinding | None:
        src, loc = node.get("source_file") or "", node.get("source_location") or ""
        m = re.fullmatch(r"L(\d+)", loc)
        if not src or not m or node.get("external"):
            return None
        start = int(m[1])
        try:
            full = safe_join(self.registry.get(repo_id).path, src)
            if not full.is_file():
                return None
            end = start if node.get("label") == src else end_line_for(full, start)  # file node: first line only
            ref = make_code_ref(repo_id, src, start, end)
            self.registry.read_source(repo_id, src, start, end)  # validate
        except RepoError:
            return None
        label = node.get("label", "")
        return CodeFinding(ref=ref, symbol=None if label == src else label, note=note)

    def _node_by_label(self, g: dict[str, Any], label: str) -> dict[str, Any] | None:
        return next((n for n in g["nodes"] if n.get("label") == label), None)

    # ---- CodeIntelligence
    def find_candidates(self, repo_id: str, query: str, limit: int = 10) -> list[CodeFinding]:
        g = self._graph(repo_id)
        toks = tokens(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for n in g["nodes"]:
            if n.get("external") or n.get("label") == n.get("source_file"):
                continue
            label = (n.get("norm_label") or n.get("label") or "").lower()
            hits = sum(1 for t in toks if t in label)
            file_hits = sum(1 for t in toks if t in (n.get("source_file") or "").lower())
            if hits or file_hits:
                scored.append((3 * hits + file_hits, n))
        scored.sort(key=lambda s: -s[0])
        out: list[CodeFinding] = []
        for score, n in scored:
            f = self._finding(repo_id, n, f"[graphify] symbol {n.get('label')} in {n.get('source_file')} (match score {score:g})")
            if f:
                out.append(f)
            if len(out) >= limit:
                break
        return out

    def read_source(self, repo_id: str, path: str, start: int, end: int) -> str:
        return self.registry.read_source(repo_id, path, start, end)

    def related(self, repo_id: str, symbol: str) -> list[CodeFinding]:
        g = self._graph(repo_id)
        node = self._node_by_label(g, symbol) or self._node_by_label(g, f"{symbol}()")
        if node is None:
            hits = [n for n in g["nodes"] if symbol.lower() in (n.get("label") or "").lower() and not n.get("external")]
            node = hits[0] if hits else None
        if node is None:
            return []
        label = node["label"]
        r = self._run("explain", label, "--all", "--graph", str(self.graph_path(repo_id)))
        out: list[CodeFinding] = []
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                m = _CONN.match(line)
                if not m or m[3] == "contains":
                    continue
                nb = self._node_by_label(g, m[2])
                if nb:
                    arrow = "calls/uses" if m[1] == "-->" else "is used by"
                    f = self._finding(repo_id, nb, f"[graphify] {label} {arrow} {nb['label']} ({m[3]})")
                    if f:
                        out.append(f)
        else:  # ambiguous (3) / no match (4): adjacency from graph.json
            ids = {n["id"]: n for n in g["nodes"]}
            for e in g["links"]:
                if e["relation"] == "contains":
                    continue
                other = e["target"] if e["source"] == node["id"] else e["source"] if e["target"] == node["id"] else None
                if other and other in ids:
                    f = self._finding(repo_id, ids[other], f"[graphify] {label} -{e['relation']}- {ids[other]['label']}")
                    if f:
                        out.append(f)
        return out

    def affected(self, repo_id: str, symbol: str, depth: int = 2) -> str:
        """Raw `graphify affected` output (reverse-dependency traversal)."""
        r = self._run("affected", symbol, "--depth", str(depth), "--graph", str(self.graph_path(repo_id)))
        return r.stdout if r.returncode == 0 else ""


def build_code_intelligence(registry: RepoRegistry, graph_root: Path, repo_id: str | None = None):
    """Graphify when it works; otherwise the labelled fallback (inspect `.backend`)."""
    from .fallback import FallbackCodeIntelligence

    gi = GraphifyCodeIntelligence(registry, graph_root)
    try:
        if not Path(gi.cli).exists():
            raise GraphifyUnavailable("graphify CLI not found")
        if repo_id:
            gi.build(repo_id)
        return gi
    except GraphifyUnavailable:
        return FallbackCodeIntelligence(registry)
