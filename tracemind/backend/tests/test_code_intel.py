import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixture_repo import make_fixture_repo
from tracemind.code import (
    FallbackCodeIntelligence,
    GraphifyCodeIntelligence,
    RepoError,
    RepoRegistry,
    build_code_intelligence,
    resolve_code_ref,
)

GRAPHIFY = shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
needs_graphify = pytest.mark.skipif(not Path(GRAPHIFY).exists(), reason="graphify CLI not installed")


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode()); h.update(p.read_bytes())
    return h.hexdigest()


def _lines(first: str, last: str) -> tuple[int, int]:
    from tests.fixture_repo import WORKER
    ls = WORKER.splitlines()
    a = next(i for i, l in enumerate(ls, 1) if l.startswith(first))
    return a, next(i for i, l in enumerate(ls, 1) if i >= a and last in l)


@pytest.fixture
def repo(tmp_path):
    return make_fixture_repo(tmp_path / "fixture-repo")


@pytest.fixture
def reg(repo):
    r = RepoRegistry()
    r.register(repo)
    return r


def test_register_captures_head_sha(repo):
    info = RepoRegistry().register(repo)
    want = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert info.head_sha == want and info.path == repo.resolve()


def test_register_rejects_bad_paths(tmp_path, repo):
    r = RepoRegistry()
    with pytest.raises(RepoError, match="does not exist"):
        r.register(tmp_path / "nope")
    with pytest.raises(RepoError, match="traversal"):
        r.register(str(repo) + "/../fixture-repo")
    plain = tmp_path / "plain"; plain.mkdir()
    with pytest.raises(RepoError, match="not a git repository"):
        r.register(plain)
    with pytest.raises(RepoError, match="not the root"):
        r.register(repo / "tests")
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(RepoError):
        r.register(tmp_path / "f.txt")


def test_register_resolves_symlink(tmp_path, repo):
    link = tmp_path / "link"; link.symlink_to(repo)
    assert RepoRegistry().register(link).path == repo.resolve()


def test_read_source_confined_and_real(reg):
    a, b = _lines("def process_message", "ack(msg)")
    txt = reg.read_source("fixture-repo", "worker.py", a, b)
    assert txt.splitlines()[0].startswith("def process_message") and "INSERT INTO notifications" in txt
    for bad in ("../x", "/etc/passwd", ".git/config", "tests/../../x"):
        with pytest.raises(RepoError):
            reg.read_source("fixture-repo", bad, 1, 1)
    with pytest.raises(RepoError, match="out of bounds"):
        reg.read_source("fixture-repo", "worker.py", 1, 999)


def test_read_source_rejects_symlink_escape(tmp_path, repo, reg):
    secret = tmp_path / "secret.txt"; secret.write_text("s3cret\n")
    (repo / "leak.txt").symlink_to(secret)
    with pytest.raises(RepoError, match="escapes"):
        reg.read_source("fixture-repo", "leak.txt", 1, 1)


def test_resolve_code_ref(reg):
    ok = resolve_code_ref(reg, "code:fixture-repo:worker.py:{}-{}".format(*_lines("def process_message", "ack(msg)")))
    assert "INSERT INTO notifications" in ok.text
    for bad in ("code:fixture-repo:worker.py:1-999", "code:fixture-repo:nofile.py:1-2", "code:other:worker.py:1-2",
                "code:fixture-repo:../x:1-2", "garbage", "code:fixture-repo:worker.py:5-2"):
        with pytest.raises(RepoError):
            resolve_code_ref(reg, bad)


def test_fallback_finds_process_message(reg):
    ci = FallbackCodeIntelligence(reg)
    assert ci.backend == "fallback"
    hits = ci.find_candidates("fixture-repo", "process_message insert notifications")
    assert hits and hits[0].symbol == "process_message" and "[fallback" in hits[0].note
    for h in hits:
        resolve_code_ref(reg, h.ref)
    rel = ci.related("fixture-repo", "process_message")
    assert any(f.symbol == "ack" for f in rel)
    callers = ci.related("fixture-repo", "ack")
    assert any(f.symbol == "process_message" for f in callers)


@needs_graphify
def test_graphify_backend_end_to_end(reg, repo, tmp_path):
    before = tree_hash(repo)
    ci = GraphifyCodeIntelligence(reg, tmp_path / "graphs", cli=GRAPHIFY)
    gp = ci.build("fixture-repo")
    assert gp.is_file() and tmp_path / "graphs" in gp.parents
    hits = ci.find_candidates("fixture-repo", "process_message insert notifications")
    assert ci.backend == "graphify"
    pm = [h for h in hits if h.symbol == "process_message()"]
    assert pm, hits
    r = resolve_code_ref(reg, pm[0].ref)
    assert "INSERT INTO notifications" in r.text and r.text.count("def process_message") == 1
    rel = ci.related("fixture-repo", "process_message()")
    assert any(f.symbol == "ack()" for f in rel), rel
    assert "process_message" in ci.affected("fixture-repo", "ack()")
    assert tree_hash(repo) == before, "graphify must not dirty the source repo"
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_factory_falls_back_when_graphify_missing(reg, tmp_path, monkeypatch):
    import tracemind.code.graphify as g
    monkeypatch.setattr(g.shutil, "which", lambda _: None)
    monkeypatch.setattr(g.Path, "home", lambda: tmp_path / "nohome")
    ci = build_code_intelligence(reg, tmp_path / "graphs", "fixture-repo")
    assert ci.backend == "fallback"
