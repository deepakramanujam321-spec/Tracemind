# Security

Status words: **VERIFIED** = a test in `tracemind/backend/tests` or `demo/tests` exercises it. **IMPLEMENTED** = present in code/config, no dedicated test found. **PARTIAL** = present with stated limits. **NOT IMPLEMENTED** = absent. This is a hackathon project that has had no external security review. Treat it as a development tool, not a hardened service.

## 1. Threat model summary

| Input | Why it is untrusted | Main risk |
|---|---|---|
| Telemetry (log lines, span names, exception messages) from OTLP ingest | Anyone who can reach `POST /v1/traces` or `/v1/logs` can write it; apps may log attacker-controlled text | Prompt injection into the investigation agents; fabricated evidence |
| Repository / source code under investigation | Registered by path; its contents are read and fed to the model and run in tests | Path escape, malicious test code, prompt injection from code comments |
| LLM output (hypotheses, patches) | Model output is not trusted | Hallucinated evidence, malicious or out-of-scope patches, a patch that "passes" falsely |
| The API itself | No authentication (section 4) | Anyone with network access can read data and trigger investigations and remediations |

## 2. Controls that exist

| Control | Where | Status |
|---|---|---|
| Telemetry text delimited as data (`<<<UNTRUSTED_DATA ... UNTRUSTED_DATA>>>`), system rules telling the model to ignore directives inside it, and escaping of forged delimiters | `tracemind/backend/tracemind/investigation/prompts.py` | VERIFIED for delimiting and for "cannot mint evidence": `tests/test_investigation.py::test_prompt_injection_in_log_is_delimited_and_cannot_mint_evidence`. This reduces, but cannot eliminate, injection risk against a real model; the tests use a scripted provider. |
| Evidence-ref guard: refs a hypothesis cites are checked via a resolver; unresolvable refs are stripped, confidence capped at 0.2 if no supporting ref remains; resolver exceptions count as unresolvable | `investigation/guard.py`; resolution in `api/service.py` (`resolve_ref`) and `GET /api/evidence/{ref}` | VERIFIED (same test file, plus `test_skeptic_rejects_unsupported_hypothesis`) |
| Secrets via environment only; `.env` is git-ignored; `.env.example` holds placeholders (`MODEL_API_KEY=` empty, local-only passwords) | `.gitignore`, `.env.example` | IMPLEMENTED. No secret scanning is configured. |
| Repo registration: rejects `..`, non-directories, non-git paths, paths that are not the repo root, repos without commits | `code/repos.py` (`RepoRegistry.register`) | VERIFIED: `tests/test_code_intel.py::test_register_rejects_bad_paths` |
| Source reads confined to the repo: rejects absolute paths, `..`, NUL, symlink escapes, and `.git` | `code/repos.py` (`safe_join`, `read_source`) | VERIFIED: `test_code_intel.py::test_read_source_rejects_symlink_escape` |
| Patch validation: rejects unsafe/absolute/traversal paths, `.git` paths, symlink/submodule entries, mode changes, binary patches, NUL bytes, oversized diffs (200,000 bytes) | `remediation/patching.py` (`validate_diff`) | VERIFIED: `tests/test_remediation.py::test_malicious_diff_rejected`, `test_remediation_real_demo.py::test_e_malicious_paths_rejected` |
| Search/replace edit confinement: resolved target must stay inside the sandbox copy, symlinks refused, search text must match exactly once, total size capped (100,000) | `remediation/patching.py` (`apply_edits`) | VERIFIED: `tests/test_remediation_edits.py` (`test_bad_edits_rejected_and_nothing_written`, `test_symlink_not_followed`) |
| Patches are applied only to a sandbox copy at the recorded SHA, never to the source repo | `remediation/engine.py` (docstring and flow) | IMPLEMENTED |
| Docker test sandbox flags: `--network none`, `--read-only`, tmpfs `/tmp` with `noexec,nosuid`, `--cap-drop ALL`, `no-new-privileges`, memory/swap/cpu/pids limits, `--user 10001:10001`, source mounted `:ro`, no host env forwarded (only `PYTHONDONTWRITEBYTECODE`, `HOME`), no `--privileged`; helper subprocesses get a minimal environment | `remediation/runner.py` (`docker_test_argv`, `clean_env`) | VERIFIED: `tests/test_remediation.py::test_docker_argv_is_hardened`, `test_container_really_has_no_network_and_readonly` (needs Docker), `test_remediation_real_demo.py::test_f_docker_hardening` |
| Strict status ladder: `verified` requires full suite exit 0 and the scenario regression test exit 0 with at least one test collected; bad fixes are not marked verified | `remediation/engine.py` | VERIFIED against the real demo repo: `tests/test_remediation_real_demo.py` |
| Human approval gate: `POST /api/remediations/{id}/approve` returns 409 unless status is `verified`; it only records `approved_at` | `api/routes.py` | VERIFIED: `tests/test_security.py::test_approve_requires_verified_remediation` |
| No auto-merge, no push, no PR creation anywhere in the backend | grep of `tracemind/backend/tracemind` shows no such code | IMPLEMENTED (by absence); see `docs/LIMITATIONS.md` |
| OTLP ingest limits: only `application/x-protobuf` (415 otherwise); only `identity` or `gzip` content-encoding; 32 MiB cap on raw and decompressed body (gzip decompression is bounded); malformed bodies return 400; storage failure returns 503 | `ingest/router.py` | VERIFIED for malformed input and gzip handling in `tests/test_ingest.py` (`test_gzip_and_logs`, `test_bad_inputs_never_crash`); whether the 32 MiB limits are tested was not confirmed |
| API authentication: bearer `TRACEMIND_API_KEY` on `/api/*`, separate `TRACEMIND_INGEST_TOKEN` on `/v1/*`, constant-time comparison, `TRACEMIND_AUTH_REQUIRED=true` fails startup when unset; `/healthz` and `/readyz` stay open. A single shared key, not per-user identity | `tracemind/backend/tracemind/security.py` | VERIFIED: `tests/test_security.py` (and a live compose run). Disabled by default for local development, with a startup warning. |
| Rate limiting: per-client token buckets for reads, for model-cost POSTs (investigate/remediate) and for ingest; `X-Forwarded-For` honoured only with `TRACEMIND_TRUST_PROXY=true`. In-memory, per process | `security.py` | VERIFIED: `tests/test_security.py` |
| Security headers on API responses, CORS closed unless `TRACEMIND_CORS_ORIGINS` allows the origin, OpenAPI/docs UI disabled | `security.py`, `main.py` | VERIFIED: `tests/test_security.py` |
| Redaction before model calls: emails, bearer tokens, JWTs, API keys, `password=`/`token=` values, URL credentials, private keys (`TRACEMIND_REDACTION=off` disables). Regex based, best effort | `security.py` (`redact`), applied in `prompts.data_block` | VERIFIED: `tests/test_security.py` for the listed shapes only |
| Backend container runs as non-root (uid 10001); Python dependencies pinned in `constraints.txt` | `tracemind/backend/Dockerfile`, `constraints.txt` | VERIFIED by a live compose run (`id -u` = 10001) |
| Command output stored in the DB is truncated to 6,000 chars per stream | `remediation/runner.py` (`truncate`) | IMPLEMENTED |

## 3. Docker socket risk (`docker-compose.remediation.yml`)

The overlay is **opt-in** (`docker compose -f docker-compose.yml -f docker-compose.remediation.yml up`). It mounts `/var/run/docker.sock` into the `tracemind-backend` container so the backend can start sibling sandbox containers. **Access to the Docker socket is equivalent to root on the host.** Anyone who can compromise the backend (and the API has no authentication) can start arbitrary containers, including privileged ones that mount the host filesystem.

- Use it only on a trusted local development machine.
- Never use it on a public-facing or shared deployment.
- The hardening in section 2 applies to the sandbox containers, not to the backend container that holds the socket.
- The overlay also needs `TRACEMIND_HOST_ROOT` set in `.env` and mounts `.tracemind/demo-repo` read-only and `.tracemind/sandbox` read-write at host-identical paths.
- The default `docker-compose.yml` does not mount the socket; without the overlay, remediation tests cannot run in Docker from inside the compose backend (see `docs/LIMITATIONS.md`).

## 4. Known gaps

- **Authentication is opt-in and shared-secret only.** With `TRACEMIND_API_KEY` / `TRACEMIND_INGEST_TOKEN` unset (the local-dev default) there is no authentication; with them set there is still no per-user identity, roles or audit log. Without a key, anyone who can reach port 8100 can read telemetry, inject telemetry, register repositories by local path (`POST /api/repositories` takes a server-side path), start model calls (cost), and approve remediations.
- **CORS and security headers:** now handled by `SecurityMiddleware` (see section 2). The web container's `nginx.conf` sets its own headers.
- **Rate limiting** is in-memory per process, so it is per replica and resets on restart.
- **No TLS** in `docker-compose.yml` (terminate it at a reverse proxy); all services speak plain HTTP/AMQP/Postgres. Compose publishes Postgres (5432), RabbitMQ (5672, 15672), the collector (4318), the backend (8100) and web ports on the host. Default placeholder credentials (`guest`/`guest` for RabbitMQ) are in `.env.example`.
- **Demo fault injection:** the demo worker honours `FAULT_INJECTION_ENABLED=true` (set in `.env.example`) and an `x-fault` header to cause a deliberate failure. Do not enable it outside the demo.
- **Secrets rotation:** no mechanism or documentation. `MODEL_API_KEY` and DB passwords are plain environment variables.
- **Telemetry may contain PII.** TraceMind stores whatever it receives and sends excerpts to the configured model provider (a third-party API for `gemma_api`). Regex redaction masks common credentials and emails before the model call, but stored data is unredacted and there is no retention policy.
- **Prompt injection is mitigated, not solved.** Source code comments and repository content are also model input; the delimiting in `prompts.py` is documented for telemetry text, and we did not verify equivalent treatment of every code excerpt.
- **LLM-generated patches** run test code from the sandbox copy. The sandbox limits blast radius (section 2) but a kernel/Docker escape is outside what this project addresses.
- Backend dependencies are pinned in `constraints.txt` (regenerate it when upgrading); Dependabot and a production `npm audit` run in CI. The `vite`/`esbuild` dev-server advisory remains (development only).
- Background investigation/remediation jobs run in in-process threads (`api/service.py`); there is no per-user quota.

## 5. Reporting a vulnerability

Please do **not** put exploit details in a public issue.

1. Preferred: open a private report through GitHub Security Advisories on this repository (Security tab, "Report a vulnerability"), if it is enabled for the repo.
2. Otherwise, open a GitHub issue titled "Security: please contact me" with **no** technical details, and the maintainer will arrange a private channel.

Include affected component, version/commit, and impact. Never include real secrets or real customer telemetry. This is a hackathon project with no SLA.
