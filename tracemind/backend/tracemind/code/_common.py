from __future__ import annotations

import ast
import re
from pathlib import Path

STOP = {"the", "a", "an", "of", "to", "in", "is", "and", "or", "for", "on", "with", "at", "by", "this", "that", "it"}


def tokens(query: str) -> list[str]:
    parts = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
    out: list[str] = []
    for p in parts:
        for t in [p, *p.split("_")]:
            t = t.lower()
            if len(t) > 2 and t not in STOP and t not in out:
                out.append(t)
    return out


def python_spans(text: str) -> dict[int, tuple[int, str]]:
    """start_line -> (end_line, name) for every def/class in a python source (empty on syntax error)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    spans: dict[int, tuple[int, str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            spans[n.lineno] = (n.end_lineno or n.lineno, n.name)
    return spans


def end_line_for(path: Path, start: int, default_len: int = 20) -> int:
    """Best-effort end line for a symbol starting at `start` (AST for .py, bounded window otherwise)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    total = len(text.splitlines())
    if path.suffix == ".py":
        sp = python_spans(text).get(start)
        if sp:
            return min(sp[0], total)
    return max(start, min(start + default_len - 1, total))
