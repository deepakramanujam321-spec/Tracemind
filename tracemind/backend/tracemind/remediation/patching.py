"""Diff validation and application. Applies ONLY inside the sandbox copy."""
from __future__ import annotations

import re
from pathlib import Path


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


def apply_edits(sandbox: Path, edits: list, max_total: int = 100_000) -> list[str]:
    """Apply exact search/replace edits inside the sandbox copy only. Raises PatchRejected on any problem and
    leaves the working tree untouched in that case (all edits are validated before anything is written)."""
    if not edits:
        raise PatchRejected("no edits")
    if sum(len(e.search) + len(e.replace) for e in edits) > max_total:
        raise PatchRejected("edits too large")
    root = sandbox.resolve()
    staged: dict[Path, str] = {}
    for e in edits:
        rel = Path(e.path)
        if rel.is_absolute() or ".." in rel.parts or any(part.startswith(".git") for part in rel.parts) or not e.path:
            raise PatchRejected(f"unsafe path {e.path!r}")
        target = (root / rel)
        # resolve symlinks of existing parents and make sure the file stays inside the sandbox
        if root not in target.resolve().parents:
            raise PatchRejected(f"path escapes sandbox: {e.path!r}")
        if target.is_symlink():
            raise PatchRejected(f"refusing to edit symlink {e.path!r}")
        text = staged.get(target)
        if text is None:
            text = target.read_text() if target.is_file() else None
        if e.search == "":
            if text is not None:
                raise PatchRejected(f"{e.path}: create requested but file exists")
            staged[target] = e.replace
            continue
        if text is None:
            raise PatchRejected(f"{e.path}: file does not exist")
        n = text.count(e.search)
        if n != 1:
            raise PatchRejected(f"{e.path}: search text must match exactly once (found {n})")
        staged[target] = text.replace(e.search, e.replace, 1)
    for target, text in staged.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return sorted(str(t.relative_to(root)) for t in staged)
