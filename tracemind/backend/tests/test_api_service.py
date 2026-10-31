"""Orchestration-level checks that need only Postgres (no model, no Docker sandbox)."""
import os

import pytest
from tracemind.api.service import Service
from tracemind.code import RepoError


@pytest.fixture()
def svc(repo):
    return Service(repo)


def test_repo_root_allowlist_rejects_outside_paths(svc, tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEMIND_REPO_ROOTS", str(tmp_path / "allowed"))
    with pytest.raises(RepoError, match="outside the allowed roots"):
        svc.register_repo(str(tmp_path))
    with pytest.raises(RepoError, match="outside the allowed roots"):
        svc.register_repo(str(tmp_path / "allowed" / ".." / "x"))


def test_reaper_fails_only_old_running_jobs(svc, monkeypatch):
    monkeypatch.setenv("TRACEMIND_JOB_TIMEOUT_S", "60")
    with svc.pool.connection() as c:
        c.execute("DELETE FROM incidents WHERE id='INC-reap'")
        c.execute("INSERT INTO incidents (id,title) VALUES ('INC-reap','t')")
        c.execute("INSERT INTO investigations (id,incident_id,status,started_at) VALUES "
                  "('inv-old','INC-reap','running', now() - interval '2 hours'), ('inv-new','INC-reap','running', now())")
    assert svc.reap_stale_jobs() >= 1
    rows = {r["id"]: r["status"] for r in svc.q("SELECT id,status FROM investigations WHERE incident_id='INC-reap'")}
    assert rows == {"inv-old": "failed", "inv-new": "running"}
    with svc.pool.connection() as c:
        c.execute("DELETE FROM incidents WHERE id='INC-reap'")
