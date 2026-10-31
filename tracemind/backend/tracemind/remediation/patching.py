"""Diff validation and application. Applies ONLY inside the sandbox copy."""
from __future__ import annotations

import re

class PatchRejected(ValueError):
    pass


_FORBIDDEN_NAMES = {".git", ".gitmodules", ".gitattributes", ".gitignore"}
_HUNK = re.compile(r"^@@ -\d+(?:,(?P<ol>\d+))? \+\d+(?:,(?P<nl>\d+))? @@")
_HEADER = re.compile(r"^(?:diff --git a/(?P<ga>.+) b/(?P<gb>.+)|(?:---|\+\+\+) (?P<p>\S.*?)(?:\t.*)?|"
                     r"(?:rename|copy) (?:from|to) (?P<r>.+)|(?:old|new) mode (?P<m>\d+)|"
                     r"(?:new|deleted) file mode (?P<fm>\d+)|GIT binary patch|Binary files .*)$")


def _check_path(p: str) -> None:
    p = p.strip().strip('"')
    if p == "/dev/null":
        return
    if p.startswith(("a/", "b/")):
        p = p[2:]
    if not p or p.startswith("/") or "\\" in p or "\x00" in p:
        raise PatchRejected(f"unsafe path in diff: {p!r}")
    parts = p.split("/")
    if ".." in parts or "." in parts and len(parts) == 1:
        raise PatchRejected(f"path traversal in diff: {p!r}")
    if any(x in _FORBIDDEN_NAMES for x in parts):
        raise PatchRejected(f"diff touches protected path: {p!r}")


def validate_diff(diff: str, max_bytes: int = 200_000) -> list[str]:
    """Reject traversal / .git / absolute paths / symlinks / binary / mode changes. Returns touched paths."""
    if not diff.strip():
        raise PatchRejected("empty diff")
    if len(diff.encode()) > max_bytes:
        raise PatchRejected("diff too large")
    if "\x00" in diff:
        raise PatchRejected("NUL byte in diff")
    paths: list[str] = []
    old_left = new_left = 0  # remaining hunk lines, by @@ counts (so '--- x' inside a hunk is body, not a header)
    for line in diff.splitlines():
        if old_left > 0 or new_left > 0:
            c = line[:1]
            if c == "\\":
                continue
            if c == " " or line == "":
                old_left -= 1; new_left -= 1
            elif c == "-":
                old_left -= 1
            elif c == "+":
                new_left -= 1
            else:
                raise PatchRejected(f"malformed hunk line: {line[:80]!r}")
            continue
        hm = _HUNK.match(line)
        if hm:
            old_left = int(hm["ol"] or 1)
            new_left = int(hm["nl"] or 1)
            continue
        m = _HEADER.match(line)
        if not m:
            if line.startswith(("index ", "similarity index", "dissimilarity index")):
                continue
            raise PatchRejected(f"unrecognised diff line: {line[:80]!r}")
        if m["ga"]:
            _check_path(m["ga"]); _check_path(m["gb"]); paths += [m["ga"], m["gb"]]
        elif m["p"]:
            _check_path(m["p"]); paths.append(m["p"])
        elif m["r"]:
            _check_path(m["r"]); paths.append(m["r"])
        elif m["m"] or m["fm"]:
            mode = m["m"] or m["fm"]
            if mode.startswith("120") or mode.startswith("160"):
                raise PatchRejected("symlink/submodule entries are not allowed")
            if m["m"]:
                raise PatchRejected("mode changes are not allowed")
        else:
            raise PatchRejected("binary patches are not allowed")
    if not paths:
        raise PatchRejected("diff touches no files")
    return sorted({p[2:] if p.startswith(("a/", "b/")) else p for p in paths if p != "/dev/null"})
