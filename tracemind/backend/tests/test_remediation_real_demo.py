"""Sandbox must never mark a bad fix 'verified' -- exercised against the REAL demo repo snapshot, real Docker."""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from tests.test_code_intel import tree_hash
from tracemind.contracts import CodeFinding, Message
from tracemind.remediation import InMemoryRemediationStore, RemediationEngine, build_image, docker_available, docker_test_argv, image_exists
from tracemind.remediation.runner import SANDBOX_IMAGE, run_in_docker

ROOT = Path(__file__).resolve().parents[3]
SUITE = "tests/test_sandbox_regression.py"   # the only offline-runnable test file in the demo repo
REG = SUITE + "::test_redelivery_is_idempotent_sandbox"
TEST_CMD = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
pytestmark = pytest.mark.skipif(not docker_available(), reason="docker not running")

INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_notification_id ON notifications (notification_id);\n"
INSERT_END = "VALUES (%s, %s, %s, %s, 'delivered')\""
ON_CONFLICT = "VALUES (%s, %s, %s, %s, 'delivered') ON CONFLICT (notification_id) DO NOTHING\""


class ScriptedProvider:
    """Test-only model double returning a fixed diff."""
    name, supports_tools = "scripted", False

    def __init__(self, diff: str) -> None:
        self.diff = diff

    def generate(self, messages: list[Message], **opts) -> str:
        return self.diff

    def generate_structured(self, messages, schema: type[BaseModel], **opts):
        return schema(diff=self.diff, explanation="scripted")


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo") / "demo-repo"
    subprocess.run([str(ROOT / "scripts/prepare_demo_repo.sh"), str(d)], check=True, capture_output=True)
    if not image_exists():
        build_image()
    return d


def make_diff(demo: Path, tmp: Path, edits: dict[str, list[tuple[str, str]]]) -> str:
    """Real git diff produced from a scratch clone, so hunks are exact."""
    scratch = tmp / "scratch"
    shutil.copytree(demo, scratch)
    for rel, pairs in edits.items():
        p = scratch / rel
        s = p.read_text()
        for old, new in pairs:
            assert old in s, (rel, old)
            s = s.replace(old, new, 1)
        p.write_text(s)
    return git(scratch, "diff", "--no-color")


SCHEMA_FIX = ("db/schema.sql", [("CREATE INDEX IF NOT EXISTS idx_notifications_user", INDEX + "CREATE INDEX IF NOT EXISTS idx_notifications_user")])
WORKER = "worker/notif_worker/worker.py"
WORKER_FIX = (WORKER, [(INSERT_END, ON_CONFLICT)])
FIND = [CodeFinding(ref="code:demo-repo:worker/notif_worker/worker.py:30-45", symbol="process_message", note="plain INSERT")]


def attempt(demo, tmp, diff, rid, baseline=True):
    before = tree_hash(demo)
    store = InMemoryRemediationStore()
    eng = RemediationEngine(ScriptedProvider(diff), store, tmp / ".sandbox", test_cmd=TEST_CMD, suite_paths=[SUITE])
    sha = git(demo, "rev-parse", "HEAD").strip()
    res = eng.run(demo, sha, "redelivery duplicate insert", ["sig:i:redelivery_duplicate_write"], FIND, REG,
                  remediation_id=rid, run_baseline=baseline)
    print(f"\n[{rid}] status={res.status} baseline_reproduced={res.baseline_reproduced} tests_passed={res.tests_passed} "
          f"regression_passed={res.regression_passed} error={res.error}")
    for c in store.commands[rid]:
        if c.phase in {"baseline_test", "test", "regression_test"}:
            tail = [l for l in c.stdout.strip().splitlines() if l.strip()][-1:]
            print(f"   {c.phase:16} exit={c.exit_code} {tail}")
    assert tree_hash(demo) == before, "source repo changed!"
    assert git(demo, "status", "--porcelain") == ""
    return res, store


def test_a_correct_fix_verified(demo, tmp_path):
    res, store = attempt(demo, tmp_path, make_diff(demo, tmp_path, dict([SCHEMA_FIX, WORKER_FIX])), "a")
    assert res.baseline_reproduced is True
    assert res.status == "verified" and res.tests_passed and res.regression_passed
    assert store.statuses["a"] == ["patch_generated", "tested", "verified"]
    base = next(c for c in store.commands["a"] if c.phase == "baseline_test")
    assert "expected exactly 1 row" in base.stdout and "got 2" in base.stdout


@pytest.mark.parametrize("rid,edits", [
    ("b_comment_only", {WORKER: [("async def process_message(message, conn):", "# TODO dedupe\nasync def process_message(message, conn):")]}),
    ("b_on_conflict_without_index", dict([WORKER_FIX])),
    ("b_unique_index_only", dict([SCHEMA_FIX])),
    ("b_unrelated_line", {WORKER: [('QUEUE = "notifications.create"', 'QUEUE = "notifications.create"  # unchanged queue')]}),
])
def test_b_wrong_fix_not_verified(demo, tmp_path, rid, edits):
    res, _ = attempt(demo, tmp_path, make_diff(demo, tmp_path, edits), rid)
    assert res.status != "verified"
    assert res.status in ("tested", None)
    if res.status == "tested":
        assert res.regression_passed is False and res.tests_passed is False


def test_c_regression_passes_but_other_test_breaks(demo, tmp_path):
    breaker = (WORKER, [("            await message.ack()\n            log.info(\"notification acked",
                         "            await message.ack()\n            if \"x-fault\" not in headers:\n"
                         "                await message.ack()\n            log.info(\"notification acked")])
    res, store = attempt(demo, tmp_path, make_diff(demo, tmp_path, {"db/schema.sql": SCHEMA_FIX[1], WORKER: WORKER_FIX[1] + breaker[1]}), "c")
    reg = next(c for c in store.commands["c"] if c.phase == "regression_test")
    assert reg.exit_code == 0, "regression test alone should pass in case (c)"   # scenario fixed ...
    assert res.tests_passed is False                                                # ... but suite broken
    assert res.status == "tested" and "verified" not in store.statuses["c"]


@pytest.mark.parametrize("rid,diff", [
    ("d_invalid", "this is not a diff at all\n"),
    ("d_not_applicable", "--- a/worker/notif_worker/worker.py\n+++ b/worker/notif_worker/worker.py\n@@ -1,3 +1,3 @@\n-nonexistent line one\n-nonexistent line two\n+x\n+y\n context\n"),
    ("d_wrong_context", "--- a/db/schema.sql\n+++ b/db/schema.sql\n@@ -1,2 +1,2 @@\n-this line is not in the file\n+x\n -- also not\n"),
])
def test_d_unapplicable_diff(demo, tmp_path, rid, diff):
    res, store = attempt(demo, tmp_path, diff, rid, baseline=False)
    assert res.status is None and res.error
    assert "patch_apply" not in [c.phase for c in store.commands[rid]] or res.error
    assert store.statuses.get(rid) is None and not res.diff
    sb = Path(res.sandbox_path)
    assert git(sb, "status", "--porcelain") == ""      # nothing applied in the sandbox either


@pytest.mark.parametrize("path", ["../evil.py", "demo/../../evil.py", ".git/config", ".git/hooks/post-checkout", "/etc/cron.d/x", "worker/../.git/HEAD"])
def test_e_malicious_paths_rejected(demo, tmp_path, path):
    diff = f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+boom\n"
    res, store = attempt(demo, tmp_path, diff, "e", baseline=False)
    assert res.status is None and "rejected" in res.error
    assert not {"patch_check", "patch_apply"} & {c.phase for c in store.commands["e"]}
    assert not (tmp_path / "evil.py").exists()


# ---------------------------------------------------------------- docker hardening checklist (live container)
@pytest.fixture
def live(demo):
    name = "tm-probe-" + str(time.time_ns())
    argv = docker_test_argv(demo, ["python", "-c", "import time; time.sleep(60)"], name)
    p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        r = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
        if r.returncode == 0 and json.loads(r.stdout)[0]["State"]["Running"]:
            break
        time.sleep(0.2)
    yield name, json.loads(r.stdout)[0]
    subprocess.run(["docker", "kill", name], capture_output=True)
    p.wait(timeout=20)


def dexec(name, *cmd):
    return subprocess.run(["docker", "exec", name, *cmd], capture_output=True, text=True)


def test_f_docker_hardening(live, demo):
    name, i = live
    hc = i["HostConfig"]
    report = {}
    report["not privileged"] = hc["Privileged"] is False
    report["cap drop ALL"] = hc["CapDrop"] == ["ALL"] and not hc["CapAdd"]
    report["no-new-privileges"] = "no-new-privileges" in " ".join(hc["SecurityOpt"] or [])
    report["read-only rootfs"] = hc["ReadonlyRootfs"] is True
    mounts = [(m["Source"], m["Destination"], m["RW"]) for m in i["Mounts"]]
    report["only mount = source, ro"] = len(mounts) == 1 and mounts[0][1] == "/work" and mounts[0][2] is False
    report["network none"] = hc["NetworkMode"] == "none"
    report["memory/swap"] = hc["Memory"] == 512 * 1024 * 1024 and hc["MemorySwap"] == hc["Memory"]
    report["cpus"] = hc["NanoCpus"] == 10**9
    report["pids"] = hc["PidsLimit"] == 128
    report["user non-root"] = i["Config"]["User"] == "10001:10001"
    uid = dexec(name, "id", "-u").stdout.strip()
    report["uid != 0 at runtime"] = uid == "10001"
    env = dexec(name, "env").stdout
    img_env = set(json.loads(subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True, text=True).stdout)[0]["Config"]["Env"])
    extra = {"HOSTNAME=" + i["Config"]["Hostname"], "PYTHONDONTWRITEBYTECODE=1", "HOME=/tmp"}
    leaked = [l for l in env.splitlines() if l not in img_env and l not in extra]
    leaked += [l for l in env.splitlines() if any(k in l.upper() for k in ("TRACEMIND", "MODEL", "POSTGRES", "TOKEN", "SECRET", "PASSWORD", "DATABASE"))]
    report["no host env leaked"] = not leaked
    net = dexec(name, "python", "-c", "import socket; socket.create_connection(('1.1.1.1',53),2)")
    report["connect attempt fails"] = net.returncode != 0 and "OSError" in net.stderr or "unreachable" in net.stderr
    ro = dexec(name, "sh", "-c", "touch /work/x 2>&1; touch /etc/x 2>&1; touch /tmp/ok && echo tmp-writable")
    report["fs read-only except tmpfs"] = "tmp-writable" in ro.stdout and ro.stdout.count("ead-only") >= 2
    print("\nCHECKLIST", json.dumps(report, indent=1), "\nmounts", mounts, "\nenv", env.splitlines())
    assert all(report.values()), report


def test_g_timeout_kills_container_and_leaves_none(demo, tmp_path):
    store = InMemoryRemediationStore()
    t0 = time.time()
    r = run_in_docker(store, "t", "probe", demo, ["python", "-c", "import time; time.sleep(120)"], timeout=4)
    time.sleep(1)
    left = subprocess.run(["docker", "ps", "-a", "--filter", "name=tm-sbx-", "-q"], capture_output=True, text=True).stdout.split()
    print("\ntimeout run: exit_code", r.exit_code, "stderr", r.stderr, "elapsed", round(time.time() - t0, 1), "leftover", left)
    assert r.exit_code is None and "TIMEOUT" in r.stderr and time.time() - t0 < 30
    assert left == []
