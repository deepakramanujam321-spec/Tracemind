"""Command execution with recording, plus hardened Docker test runner."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import CommandRun, RemediationStore

MAX_OUT = 6000
SANDBOX_IMAGE = "tracemind-sandbox:latest"
DOCKERFILE = Path(__file__).parent / "sandbox" / "Dockerfile.sandbox"


def truncate(s: str, limit: int = MAX_OUT) -> str:
    if len(s) <= limit:
        return s
    h = limit // 2
    return s[:h] + f"\n...[truncated {len(s) - limit} chars]...\n" + s[-h:]


def clean_env() -> dict[str, str]:
    """Minimal env for host-side helper processes (git/docker CLI). No secrets passed through."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": "/dev/null"}
    if "DOCKER_HOST" in os.environ:
        env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    return env


def run_recorded(store: RemediationStore, rid: str, phase: str, argv: list[str], *, cwd: Path | None = None,
                 timeout: float = 120, input_text: str | None = None, on_timeout: list[str] | None = None) -> CommandRun:
    start = time.monotonic()
    started = datetime.now(timezone.utc)
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=clean_env(), input=input_text)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        code, out, err = None, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), \
            f"TIMEOUT after {timeout}s"
        if on_timeout:
            subprocess.run(on_timeout, capture_output=True, env=clean_env())
    run = CommandRun(phase=phase, command=argv, exit_code=code, stdout=truncate(out), stderr=truncate(err),
                     started_at=started, duration_ms=(time.monotonic() - start) * 1000)
    store.record_command(rid, run)
    return run


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20, env=clean_env()).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def image_exists(image: str = SANDBOX_IMAGE) -> bool:
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True, env=clean_env()).returncode == 0


def build_image(image: str = SANDBOX_IMAGE) -> None:
    """Controlled, networked build step (the only time the sandbox image touches the network)."""
    subprocess.run(["docker", "build", "-t", image, "-f", str(DOCKERFILE), str(DOCKERFILE.parent)],
                   check=True, capture_output=True, env=clean_env(), timeout=600)


def docker_test_argv(workdir: Path, test_cmd: list[str], name: str, image: str = SANDBOX_IMAGE,
                     memory: str = "512m", cpus: str = "1", pids: int = 128) -> list[str]:
    """No --privileged, no network, read-only root + read-only source mount, tmpfs scratch, all caps dropped,
    no host env (docker run does not forward the host environment; only explicit -e below)."""
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", memory, "--memory-swap", memory, "--cpus", cpus, "--pids-limit", str(pids),
        "--user", "10001:10001",
        "-v", f"{workdir}:/work:ro", "-w", "/work",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
        image, *test_cmd,
    ]


def run_in_docker(store: RemediationStore, rid: str, phase: str, workdir: Path, test_cmd: list[str],
                  timeout: float = 120, image: str = SANDBOX_IMAGE) -> CommandRun:
    name = f"tm-sbx-{uuid.uuid4().hex[:12]}"
    return run_recorded(store, rid, phase, docker_test_argv(workdir, test_cmd, name, image), timeout=timeout,
                        on_timeout=["docker", "kill", name])
