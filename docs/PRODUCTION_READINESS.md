# Production readiness

Honest status as of this commit. Effort figures are rough single-engineer estimates, not commitments.

**Verdict:** safe to run for a small trusted team behind a TLS reverse proxy, on telemetry you are willing to send to the
model provider. **Not ready** for a shared or multi-tenant service or for untrusted users, mainly because of the Docker-socket
remediation model, in-process jobs and the single shared API key.

## Done in this pass

| Area | What changed | Verified by |
|---|---|---|
| Authentication | Bearer `TRACEMIND_API_KEY` on `/api/*`, separate `TRACEMIND_INGEST_TOKEN` on `/v1/*`, constant-time compare; `TRACEMIND_AUTH_REQUIRED=true` refuses to start without them. Collector sends the ingest token. UI prompts for the key on 401 (kept in sessionStorage). | `tests/test_security.py`; live compose run (401 without key, 200 with, collector ingest accepted) |
| Rate limiting | Per-client token buckets: reads, model-cost POSTs (investigate/remediate) and ingest each have their own budget. `X-Forwarded-For` ignored unless `TRACEMIND_TRUST_PROXY=true`. | `tests/test_security.py` |
| Headers / CORS | Security headers on every API response; CORS closed unless `TRACEMIND_CORS_ORIGINS` lists the origin; OpenAPI/docs UI disabled. | `tests/test_security.py` |
| Privacy | Emails, bearer tokens, JWTs, API keys, `password=`-style values and URL credentials are masked before any text goes to the model provider (`TRACEMIND_REDACTION=off` to disable). | `tests/test_security.py` |
| Probes | `/healthz` (liveness) and `/readyz` (DB reachable, 503 otherwise). | `tests/test_security.py`, compose healthcheck |
| Approval gate | Previously untested: now tested (409 unless `verified`, 404 unknown, `approved_at` only set on success). | `tests/test_security.py` |
| Container | Backend runs as non-root uid 10001; Python dependencies pinned in `constraints.txt` (resolved on `python:3.12-slim`). | live compose run |
| Supply chain | `react-router-dom` upgraded to 7.18.5 (two advisories); production `npm audit` is clean; Dependabot added for npm, pip, Docker, Actions. | `npm audit --omit=dev` |
| CI | Ruff lint, production npm audit and compose validation added; ruff config committed and existing findings fixed (including missing `raise ... from`). | CI config; `ruff check` clean |

Tests: 111 passed, 1 skipped (was 90 passed, 1 skipped).

## Still required before a real production deployment

Ordered by how much risk each removes.

| # | Gap | Why it matters | Effort |
|---|---|---|---|
| 1 | **Remediation runner isolation.** Sandbox needs the host Docker socket (root-equivalent). Move test execution to a separate worker on an isolated host/VM (or rootless Docker / gVisor / a Kubernetes Job), reached over an authenticated queue; backend gets no socket. | The largest remaining security risk. | 1-2 weeks |
| 2 | **TLS and real identity.** Terminate TLS at a proxy (Caddy/nginx/ALB); replace the shared key with per-user SSO (OIDC), roles (viewer / investigator / approver) and an audit log of who approved what. | One shared secret has no accountability or revocation per person. | 1-2 weeks |
| 3 | **Durable job queue.** Investigations/remediations run in daemon threads and are lost on restart (reaped after 30 min). Use a queue (Postgres `SKIP LOCKED`, Redis/RQ, or Celery) with retries and cancellation. | Reliability; also required for #1. | 1 week |
| 4 | **Data lifecycle.** Retention/partitioning for spans and logs, backups and restore drill, HA Postgres. Redaction is regex-based best effort; add an allow-list mode and a documented data-processing note for the model provider. | Unbounded growth; privacy/compliance. | 1 week |
| 5 | **Generality of correlation and model quality.** Signals were built for one scenario (redelivery duplicate write). Needs more failure classes (timeouts, retries storms, N+1, deadlocks, config drift) and an evaluation set that scores root-cause accuracy and fix-verification rates per model. The local OpenAI-compatible provider is untested. | The product value; currently proven on one incident. | 3-6 weeks |
| 6 | **Self-observability.** TraceMind emits no metrics or traces of its own; logs are unstructured. Add request/job metrics, structured JSON logs, alerts on failed jobs and ingest errors. | You cannot operate what you cannot see. | 3-5 days |
| 7 | **Load and scale.** No load test exists, and `/api/incidents` has no pagination. Needs a load test of ingest and the API, pagination, and an index review. | Unknown capacity. | 1 week |
| 8 | **Deployment artifacts.** No Helm chart/Terraform; compose publishes dev ports and default credentials. Needs a prod compose or chart with secrets from a secret manager, no published DB/queue ports, resource requests. | Repeatable, safe rollout. | 3-5 days |
| 9 | **Frontend tests.** No unit or end-to-end tests for the UI (only a production build). Add Vitest + Playwright for the investigate and approve flows. | Regression safety. | 3-5 days |
| 10 | **Feature gaps promised by the pitch.** GitHub PR creation (approval currently only records `approved_at`), metrics ingestion, model tool calling. | Completes the "fix to PR" story; PR creation needs a GitHub App credential. | 1-2 weeks |
| 11 | **Prompt-injection coverage.** Telemetry is delimited and tested; confirm and test the same treatment for source excerpts. Add an adversarial test set. | Residual model-manipulation risk. | 3-5 days |
| 12 | **Dev-tooling advisory.** `vite`/`esbuild` (dev server only, not shipped) needs a major Vite upgrade. | Developer machines only. | 1-2 days |

Rough total for a hardened, supportable v1 (items 1-9): about 8-12 engineer-weeks. Items 5 and 10 are open-ended.

## Minimal safe configuration today

```bash
# .env
TRACEMIND_API_KEY=$(openssl rand -hex 32)
TRACEMIND_INGEST_TOKEN=$(openssl rand -hex 32)
TRACEMIND_AUTH_REQUIRED=true
TRACEMIND_TRUST_PROXY=true        # only if a reverse proxy you control sets X-Forwarded-For
```

Put a TLS-terminating proxy in front of ports 5174/8100/4318, do not publish Postgres/RabbitMQ, and do not use
`docker-compose.remediation.yml` on any shared machine.
