"""Repository registration: validate a local path, resolve it, capture HEAD SHA."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RepoError(ValueError):
    """Invalid or unsafe repository / path."""


@dataclass(frozen=True)
class RepoInfo:
    repo_id: str
    path: Path          # realpath of the git toplevel
    head_sha: str


def git(path: Path, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout, env=env)


def safe_join(root: Path, rel: str) -> Path:
    """Join rel under root; reject absolute paths, traversal, NUL and symlink escapes."""
    if not rel or "\x00" in rel:
        raise RepoError("empty or invalid path")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise RepoError(f"path escapes repository: {rel!r}")
    root_real = root.resolve()
    full = (root_real / p).resolve()
    if full != root_real and root_real not in full.parents:
        raise RepoError(f"path escapes repository: {rel!r}")
    return full


class RepoRegistry:
    def __init__(self) -> None:
        self._repos: dict[str, RepoInfo] = {}

    def register(self, path: str | os.PathLike[str], repo_id: str | None = None) -> RepoInfo:
        raw = os.fspath(path)
        if not raw or "\x00" in raw:
            raise RepoError("empty or invalid repository path")
        if ".." in Path(raw).parts:
            raise RepoError("path traversal ('..') is not allowed in repository path")
        p = Path(raw).expanduser()
        if not p.exists():
            raise RepoError(f"repository path does not exist: {raw}")
        real = p.resolve(strict=True)
        if not real.is_dir():
            raise RepoError(f"repository path is not a directory: {raw}")
        top = git(real, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            raise RepoError(f"not a git repository: {raw}")
        if Path(top.stdout.strip()).resolve() != real:
            raise RepoError(f"path is not the root of a git repository: {raw}")
        sha = git(real, "rev-parse", "HEAD")
        if sha.returncode != 0:
            raise RepoError("repository has no commits (cannot capture HEAD SHA)")
        rid = repo_id or re.sub(r"[^A-Za-z0-9_.-]", "-", real.name) or "repo"
        if ":" in rid or "/" in rid:
            raise RepoError("repo_id must not contain ':' or '/'")
        existing = self._repos.get(rid)
        if existing and existing.path != real:
            rid = f"{rid}-{hashlib.sha1(str(real).encode()).hexdigest()[:6]}"
        info = RepoInfo(rid, real, sha.stdout.strip())
        self._repos[rid] = info
        return info

    def get(self, repo_id: str) -> RepoInfo:
        try:
            return self._repos[repo_id]
        except KeyError:
            raise RepoError(f"unknown repository: {repo_id!r}") from None

    def refresh_head(self, repo_id: str) -> RepoInfo:
        info = self.get(repo_id)
        sha = git(info.path, "rev-parse", "HEAD").stdout.strip()
        self._repos[repo_id] = RepoInfo(info.repo_id, info.path, sha)
        return self._repos[repo_id]

    def read_source(self, repo_id: str, path: str, start: int, end: int) -> str:
        """Exact lines start..end (1-based, inclusive) of a file confined to the repo."""
        info = self.get(repo_id)
        full = safe_join(info.path, path)
        if not full.is_file():
            raise RepoError(f"no such file: {path}")
        parts = full.relative_to(info.path).parts
        if ".git" in parts:
            raise RepoError("access to .git is not allowed")
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        if start < 1 or end < start or end > len(lines):
            raise RepoError(f"line range {start}-{end} out of bounds for {path} ({len(lines)} lines)")
        return "\n".join(lines[start - 1 : end])

    def tracked_files(self, repo_id: str) -> list[str]:
        info = self.get(repo_id)
        out = git(info.path, "ls-files", "-z")
        if out.returncode != 0:
            return []
        return [f for f in out.stdout.split("\0") if f]
