"""Auth, rate limiting, headers/CORS and redaction. The middleware tests need no database."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tracemind.investigation import prompts
from tracemind.security import SecurityMiddleware, TokenBucket, check_startup_config, redact


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview():
        return {"ok": True}

    @app.post("/api/incidents/INC-1/investigations")
    def inv():
        return {"ok": True}

    @app.post("/v1/traces")
    def traces():
        return {"ok": True}

    return app


def test_auth_off_by_default_for_local_dev(monkeypatch):
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    assert TestClient(make_app()).get("/api/overview").status_code == 200


def test_api_requires_bearer_when_configured(monkeypatch):
    monkeypatch.setenv("TRACEMIND_API_KEY", "s3cret-key")
    c = TestClient(make_app())
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "s3cret-key"}).status_code == 401  # scheme required
    r = c.get("/api/overview", headers={"Authorization": "Bearer s3cret-key"})
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert c.get("/api/overview").headers["www-authenticate"].startswith("Bearer")


def test_health_is_always_open(monkeypatch):
    monkeypatch.setenv("TRACEMIND_API_KEY", "k")
    monkeypatch.setenv("TRACEMIND_INGEST_TOKEN", "t")
    assert TestClient(make_app()).get("/healthz").status_code == 200


def test_ingest_uses_its_own_token(monkeypatch):
    monkeypatch.setenv("TRACEMIND_API_KEY", "api")
    monkeypatch.setenv("TRACEMIND_INGEST_TOKEN", "ingest")
    c = TestClient(make_app())
    assert c.post("/v1/traces").status_code == 401
    assert c.post("/v1/traces", headers={"Authorization": "Bearer api"}).status_code == 401  # API key is not an ingest key
    assert c.post("/v1/traces", headers={"Authorization": "Bearer ingest"}).status_code == 200
    assert c.get("/api/overview", headers={"Authorization": "Bearer ingest"}).status_code == 401


def test_heavy_endpoints_have_a_tighter_limit(monkeypatch):
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMIND_HEAVY_LIMIT_PER_MIN", "2")
    c = TestClient(make_app())
    codes = [c.post("/api/incidents/INC-1/investigations").status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    assert c.get("/api/overview").status_code == 200  # reads are on a separate budget
    r = c.post("/api/incidents/INC-1/investigations")
    assert int(r.headers["retry-after"]) >= 1


def test_read_limit(monkeypatch):
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMIND_RATE_LIMIT_PER_MIN", "3")
    c = TestClient(make_app())
    assert [c.get("/api/overview").status_code for _ in range(5)] == [200, 200, 200, 429, 429]


def test_token_bucket_refills():
    t = [0.0]
    b = TokenBucket(60, clock=lambda: t[0])
    assert all(b.take("a") == 0 for _ in range(60))
    assert b.take("a") > 0
    t[0] += 2.0
    assert b.take("a") == 0
    assert b.take("other") == 0  # keys are independent


def test_cors_only_for_allowed_origins(monkeypatch):
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMIND_CORS_ORIGINS", "https://ui.example.com")
    c = TestClient(make_app())
    ok = c.get("/api/overview", headers={"Origin": "https://ui.example.com"})
    assert ok.headers["access-control-allow-origin"] == "https://ui.example.com"
    bad = c.get("/api/overview", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    pre = c.options("/api/overview", headers={"Origin": "https://ui.example.com"})
    assert pre.status_code == 204


def test_forwarded_for_ignored_unless_proxy_trusted(monkeypatch):
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMIND_RATE_LIMIT_PER_MIN", "2")
    c = TestClient(make_app())
    codes = [c.get("/api/overview", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]  # spoofing the header does not dodge the limit


def test_required_auth_refuses_to_start_without_keys(monkeypatch):
    monkeypatch.setenv("TRACEMIND_AUTH_REQUIRED", "true")
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMIND_INGEST_TOKEN", "x")
    with pytest.raises(RuntimeError, match="TRACEMIND_API_KEY"):
        check_startup_config()
    monkeypatch.setenv("TRACEMIND_API_KEY", "y")
    check_startup_config()


@pytest.mark.parametrize("raw,leak", [
    ("user bob@example.com failed", "bob@example.com"),
    ("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
    ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
    ("db postgresql://app:Sup3rSecret@db:5432/app", "Sup3rSecret"),
    ("key AIzaSyA1234567890abcdefghijklmnopqrstuvw", "AIzaSyA1234567890"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "eyJhbGciOiJIUzI1NiJ9"),
    ("api_key=abcd1234efgh", "abcd1234efgh"),
])
def test_redaction_masks_secrets(raw, leak):
    out = redact(raw)
    assert leak not in out and "REDACTED" in out


def test_redaction_preserves_evidence_refs_and_timestamps():
    s = "span:4bf92f3577b34da6a3ce929d0e0e4736 sig:INC-1:redelivery log:42 ts=1730000000123 code:r1:app/main.py:10-20"
    assert redact(s) == s


def test_prompts_redact_before_leaving_the_process():
    block = prompts.data_block("incident_context", "failed for carol@corp.io token=abcdef123456")
    assert "carol@corp.io" not in block and "abcdef123456" not in block


def test_redaction_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TRACEMIND_REDACTION", "off")
    assert redact("a@b.co") == "a@b.co"


# ---- approval gate (needs Postgres) ----------------------------------------------------------------------------

def test_approve_requires_verified_remediation(migrated, monkeypatch):
    import psycopg

    from tracemind.main import app

    monkeypatch.setenv("TRACEMIND_DATABASE_URL", migrated)
    monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)
    monkeypatch.delenv("TRACEMIND_INGEST_TOKEN", raising=False)
    with psycopg.connect(migrated, autocommit=True) as c:
        c.execute("DELETE FROM incidents WHERE id='INC-appr'")
        c.execute("INSERT INTO repositories (id,name,path,commit_sha) VALUES ('repo-appr','r','/x','abc') "
                  "ON CONFLICT (id) DO NOTHING")
        c.execute("INSERT INTO incidents (id,title) VALUES ('INC-appr','t')")
        c.execute("INSERT INTO investigations (id,incident_id,status) VALUES ('inv-appr','INC-appr','completed')")
        for rid, st in (("rem-bad", "failed"), ("rem-ok", "verified")):
            c.execute("INSERT INTO remediations (id,investigation_id,repository_id,base_sha,status) "
                      "VALUES (%s,'inv-appr','repo-appr','abc',%s)", (rid, st))
    with TestClient(app) as client:
        assert client.get("/readyz").json() == {"status": "ready"}
        assert client.post("/api/remediations/rem-bad/approve").status_code == 409
        assert client.post("/api/remediations/nope/approve").status_code == 404
        r = client.post("/api/remediations/rem-ok/approve")
        assert r.status_code == 200
    with psycopg.connect(migrated, autocommit=True) as c:
        assert c.execute("SELECT approved_at FROM remediations WHERE id='rem-bad'").fetchone()[0] is None
        assert c.execute("SELECT approved_at FROM remediations WHERE id='rem-ok'").fetchone()[0] is not None
        c.execute("DELETE FROM incidents WHERE id='INC-appr'")
