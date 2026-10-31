import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from tracemind.store import PostgresTelemetryRepository, migrate

sys.path.insert(0, str(Path(__file__).parent))  # lets tests import scripted_provider, fixtures

PORT = int(os.environ.get("TM_TEST_PG_PORT", "56789"))


@pytest.fixture(scope="session")
def pg_dsn():
    """Throwaway postgres:16 container (own name, non-5432 port); removed at session end."""
    if os.environ.get("TM_TEST_DSN"):
        yield os.environ["TM_TEST_DSN"]
        return
    name = f"tm-test-pg-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=t",
                    "-e", "POSTGRES_DB=tracemind", "-p", f"{PORT}:5432", "postgres:16"], check=True,
                   capture_output=True)
    dsn = f"postgresql://postgres:t@localhost:{PORT}/tracemind"
    try:
        for _ in range(60):
            try:
                psycopg.connect(dsn, connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                time.sleep(1)
        else:
            raise RuntimeError("postgres did not start")
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="session")
def migrated(pg_dsn):
    migrate(pg_dsn)
    return pg_dsn


@pytest.fixture()
def repo(migrated):
    with psycopg.connect(migrated, autocommit=True) as c:
        c.execute("TRUNCATE spans, span_events, logs, services CASCADE")
    r = PostgresTelemetryRepository(migrated)
    yield r
    r.close()
