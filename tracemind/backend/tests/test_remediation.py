import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from tests.fixture_repo import make_fixture_repo, real_fix_diff
from tests.test_code_intel import tree_hash
from tracemind.contracts import CodeFinding, Message
from tracemind.remediation import (
    InMemoryRemediationStore,
    PatchRejected,
    RemediationEngine,
    build_image,
    docker_available,
    docker_test_argv,
    image_exists,
    validate_diff,
)

docker = pytest.mark.skipif(not docker_available(), reason="docker not running")


class ScriptedProvider:
    """Test double: returns a fixed PatchProposal (stands in for the real model)."""
    name = "scripted"
    supports_tools = False

    def __init__(self, diff: str) -> None:
        self.diff, self.seen = diff, []

    def generate(self, messages: list[Message], **opts) -> str:
        return self.diff

    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts) -> BaseModel:
        self.seen.append(messages)
        return schema(diff=self.diff, explanation="scripted")


@pytest.fixture(scope="session")
def image():
    if docker_available() and not image_exists():
        build_image()
    return True


@pytest.fixture
def repo(tmp_path):
    return make_fixture_repo(tmp_path / "src" / "fixture-repo")


def sha(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


FINDINGS = [CodeFinding(ref="code:fixture-repo:worker.py:11-15", symbol="process_message", note="plain INSERT, no UNIQUE")]


@docker
def test_fix_is_verified_in_sandbox_and_source_untouched(tmp_path, repo, image):
    before = tree_hash(repo)
    store = InMemoryRemediationStore()
    model = ScriptedProvider(real_fix_diff(tmp_path))
    eng = RemediationEngine(model, store, tmp_path / ".sandbox")
    res = eng.run(repo, sha(repo), "redelivered message re-inserted; no UNIQUE", ["sig:inc1:redelivery_duplicate_write"],
                  FINDINGS, "tests/test_redelivery.py", remediation_id="r1")
    print("\nSTATUS", res.status, "baseline_reproduced", res.baseline_reproduced)
    for c in store.commands["r1"]:
        print(c.phase, c.exit_code, " ".join(c.command)[:110], "|", c.stdout.strip().splitlines()[-1:] if c.stdout.strip() else "")
    assert res.baseline_reproduced is True               # regression test FAILS on unpatched code
    assert res.status == "verified" and res.tests_passed and res.regression_passed
    assert store.statuses["r1"] == ["patch_generated", "tested", "verified"]
    assert "ON CONFLICT(order_id) DO NOTHING" in res.diff and store.diffs["r1"] == res.diff
    assert "UNIQUE" in (Path(res.sandbox_path) / "worker.py").read_text()
    phases = [c.phase for c in store.commands["r1"]]
    assert {"baseline_test", "patch_check", "patch_apply", "test", "regression_test"} <= set(phases)
    base = next(c for c in store.commands["r1"] if c.phase == "baseline_test")
    assert base.exit_code == 1 and "failed" in base.stdout
    assert tree_hash(repo) == before                      # source repo byte-identical
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
    assert "process_message" in model.seen[0][1].content  # code context given to the model


@docker
def test_noop_patch_is_tested_not_verified(tmp_path, repo, image):
    diff = ("--- a/worker.py\n+++ b/worker.py\n@@ -1,2 +1,2 @@\n-\"\"\"FIXTURE notification worker (test fixture, not the real demo app).\"\"\"\n"
            "+\"\"\"FIXTURE worker, comment-only change.\"\"\"\n import sqlite3\n")
    store = InMemoryRemediationStore()
    res = RemediationEngine(ScriptedProvider(diff), store, tmp_path / ".sandbox").run(
        repo, sha(repo), "x", [], FINDINGS, "tests/test_redelivery.py", remediation_id="r2")
    assert res.status == "tested" and res.regression_passed is False
    assert store.statuses["r2"] == ["patch_generated", "tested"]


@docker
@pytest.mark.parametrize("bad_path", ["../evil.py", ".git/hooks/pre-commit", "/etc/passwd", "a/../../x"])
def test_malicious_diff_rejected(tmp_path, repo, image, bad_path):
    before = tree_hash(repo)
    diff = f"diff --git a/{bad_path} b/{bad_path}\nnew file mode 100644\n--- /dev/null\n+++ b/{bad_path}\n@@ -0,0 +1 @@\n+boom\n"
    store = InMemoryRemediationStore()
    res = RemediationEngine(ScriptedProvider(diff), store, tmp_path / ".sandbox").run(
        repo, sha(repo), "x", [], FINDINGS, "tests/test_redelivery.py", remediation_id="r3", run_baseline=False)
    assert res.status is None and "rejected" in res.error
    assert "patch_apply" not in [c.phase for c in store.commands["r3"]]
    assert tree_hash(repo) == before
    assert not (tmp_path / ".sandbox" / "evil.py").exists() and not (tmp_path / "evil.py").exists()


def test_validate_diff_variants():
    ok = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert validate_diff(ok) == ["x.py"]
    # second file in a plain (no 'diff --git') multi-file diff must be checked too
    two = ok + "--- a/y.py\n+++ b/../y.py\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PatchRejected):
        validate_diff(two)
    # a removed line that looks like a header must not hide a real header
    sneaky = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,1 @@\n--- a/../z\n+b\n--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PatchRejected):
        validate_diff(sneaky)
    for bad in ["", "garbage", "diff --git a/l b/l\nnew file mode 120000\n--- /dev/null\n+++ b/l\n@@ -0,0 +1 @@\n+/etc/passwd\n",
                "diff --git a/x b/x\nGIT binary patch\nliteral 1\n", "--- a/.gitmodules\n+++ b/.gitmodules\n@@ -1 +1 @@\n-a\n+b\n"]:
        with pytest.raises(PatchRejected):
            validate_diff(bad)


def test_docker_argv_is_hardened(tmp_path):
    a = docker_test_argv(tmp_path, ["pytest"], "n")
    j = " ".join(a)
    for want in ["--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--memory ",
                 "--cpus ", "--pids-limit ", f"{tmp_path}:/work:ro"]:
        assert want in j
    assert "--privileged" not in j and "--env-file" not in j and a.count("-v") == 1


def test_sandbox_inside_source_repo_refused(tmp_path, repo):
    eng = RemediationEngine(ScriptedProvider(""), InMemoryRemediationStore(), repo / ".sandbox")
    with pytest.raises(ValueError):
        eng.create_sandbox("r", repo, sha(repo))
    assert not (repo / ".sandbox").exists()


@docker
def test_container_really_has_no_network_and_readonly(tmp_path, image):
    from tracemind.remediation.runner import run_in_docker
    store = InMemoryRemediationStore()
    (tmp_path / "w").mkdir()
    code = ("import socket,sys\n"
            "try:\n socket.create_connection(('1.1.1.1',53),2); print('NET')\nexcept OSError: print('nonet')\n"
            "try:\n open('/work/x','w'); print('WROTE')\nexcept OSError: print('ro')\n"
            "import os; print('SECRET' in os.environ)\n")
    r = run_in_docker(store, "d", "probe", tmp_path / "w", ["python", "-c", code])
    assert r.stdout.split() == ["nonet", "ro", "False"], (r.stdout, r.stderr)
