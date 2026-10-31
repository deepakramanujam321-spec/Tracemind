"""code:<repo>:<path>:<a>-<b> evidence refs."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .repos import RepoError, RepoRegistry

_REF = re.compile(r"^code:(?P<repo>[^:]+):(?P<path>.+):(?P<a>\d+)-(?P<b>\d+)$")


@dataclass(frozen=True)
class ResolvedCodeRef:
    repo_id: str
    path: str
    start: int
    end: int
    text: str


def make_code_ref(repo_id: str, path: str, start: int, end: int) -> str:
    return f"code:{repo_id}:{path}:{start}-{end}"


def parse_code_ref(ref: str) -> tuple[str, str, int, int]:
    m = _REF.match(ref)
    if not m:
        raise RepoError(f"malformed code ref: {ref!r}")
    return m["repo"], m["path"], int(m["a"]), int(m["b"])


def resolve_code_ref(registry: RepoRegistry, ref: str) -> ResolvedCodeRef:
    """Raise RepoError unless the ref points at lines that really exist in the registered repo."""
    repo, path, a, b = parse_code_ref(ref)
    text = registry.read_source(repo, path, a, b)
    return ResolvedCodeRef(repo, path, a, b, text)
