# Known limitations

Statuses: IMPLEMENTED / PARTIAL / NOT IMPLEMENTED. Anything unverified is marked as such.

| Area | Status | Detail |
|---|---|---|
| Authentication / authorization | NOT IMPLEMENTED | No auth on `/api/*`, `/v1/traces`, `/v1/logs`. See `docs/SECURITY.md`. |
| Multi-tenancy | NOT IMPLEMENTED | Single tenant; one shared set of tables, no tenant column assumed in the API. |
| Load / scale | Not tested | No load test exists in `tracemind/backend/tests`. Storage is one Postgres instance; the repository is behind a Protocol so another store could replace it (`docs/ARCHITECTURE.md` section 4), but none exists. |
| Model quality | Dependency | Hypotheses and patches are only as good as the configured model. Guards (evidence-ref resolution, patch validation, test verification) reject some bad output but cannot make a weak model correct. |
| Model API (Gemma) | PARTIAL | Live-verified with `gemma-4-31b-it` through the Gemini API (see `docs/models.md`); the local OpenAI-compatible provider is NOT live-tested. Availability, cost, quotas and latency (minutes per investigation with thinking enabled) depend on the provider, and results vary with model quality. |
| Structured output | PARTIAL | JSON-in-prompt plus Pydantic validation and bounded retry (default 2); no provider-native schema enforcement. |
| Tool calling | NOT IMPLEMENTED | `generate_with_tools` is not implemented; `supports_tools=False` for both providers. |
| GitHub PR creation | NOT IMPLEMENTED | Approval only sets `approved_at` (`api/routes.py`). Nothing is pushed or opened. |
| Metrics ingestion | NOT IMPLEMENTED | OTLP traces and logs only (`ingest/router.py` has `/v1/traces` and `/v1/logs`). |
| Sandbox scope | PARTIAL | Tests run with `--network none`, so only offline tests can run. Tests that need Postgres/RabbitMQ cannot run in the sandbox; the redelivery bug is checked through an offline sandbox variant in `demo/tests/test_sandbox_regression.py`, not the full integration test. |
| Sandbox availability in compose | PARTIAL | Needs Docker and the sandbox image. The default compose backend has no Docker access; the opt-in `docker-compose.remediation.yml` mounts the Docker socket (see `docs/SECURITY.md` section 3). |
| Code graph (Graphify) | PARTIAL | AST-only code graphs (no LLM extraction), recording start lines only; evidence refs still resolve against actual file contents. When Graphify is unavailable the code falls back to plain source inspection (`code/fallback.py`, labelled as such per `docs/ARCHITECTURE.md` section 10). |
| Background jobs | PARTIAL | Investigations and remediations run in in-process daemon threads (`api/service.py`), not a durable queue. Jobs in flight are lost on restart; at backend start, `running`/`pending` rows older than `TRACEMIND_JOB_TIMEOUT_S` (default 1800 s) are marked `failed` (`Service.reap_stale_jobs`, covered by `tests/test_api_service.py`). Concurrent jobs are bounded per process by `TRACEMIND_MAX_CONCURRENT_JOBS`. |
| Correlation scope | PARTIAL | The deterministic signals were built around the demo scenario (redelivery duplicate write). Generality to other failure classes is untested. |
| Telemetry privacy | Gap | Stored telemetry may contain PII and is sent to the model provider; no redaction or retention policy. |
| Docker socket | Risk | Equivalent to root on host when the remediation overlay is used. Trusted dev machines only. |
| Transport security | NOT IMPLEMENTED | No TLS in `docker-compose.yml`; no rate limiting. |
| Cloudways deployment | Not viable as-is | Per the research in `docs/DEPLOYMENT.md` (untested, partly secondary sources): no documented Docker or root, Python apps reported unsupported, MySQL/MariaDB only on Flexible, so at best the frontend can sit there; the backend, Postgres, collector, demo app and sandbox need a Docker VPS or similar. |
| Persistence of tool state | Note | Sandbox copies and registered repos live under `.tracemind/` and `.sandbox/` (git-ignored). |
