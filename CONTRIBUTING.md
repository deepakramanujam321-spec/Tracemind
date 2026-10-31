# Contributing to TraceMind

TraceMind is MIT licensed (see `LICENSE`). Contributions are welcome; this is a hackathon-stage project, so expect rough edges.

## Repo layout and ownership

Source of truth: `docs/ARCHITECTURE.md` (change it first, then code).

| Path | Area |
|---|---|
| `demo/api`, `demo/worker`, `demo/web`, `demo/db` | Demo notification app (telemetry producer, contains the deliberate bug) |
| `infra/collector`, `tracemind/backend/tracemind/ingest`, `.../store` | OTLP ingestion, normalization, persistence |
| `tracemind/backend/tracemind/investigation`, `.../models` | LangGraph agents, model providers |
| `tracemind/backend/tracemind/code`, `.../remediation` | Code graph, repo access, sandbox, patching |
| `tracemind/web` | React + TypeScript UI |
| `docker-compose.yml`, `docker-compose.remediation.yml`, `infra/postgres`, `scripts/` | Orchestration and scripts |
| `docs/`, `tracemind/backend/migrations`, `tracemind/backend/tracemind/api`, `tracemind/backend/tracemind/main.py` | Contracts, API routers, wiring |

The architecture doc's rule is to avoid editing areas you do not own and to request cross-area changes from the orchestrator. Shared contracts live in `tracemind/backend/tracemind/contracts.py`; import them, do not fork them. Schema changes are additive numbered files in `tracemind/backend/migrations`.

## Dev setup

Prerequisites: Python 3.11+ (the backend image uses 3.12), Node, Docker (for the compose stack and sandbox tests), `uv`.

```bash
cp .env.example .env            # then edit; never commit .env
# backend
uv venv .venv
uv pip install -e "tracemind/backend[dev]"      # run from repo root; scripts/test_all.sh expects .venv/bin/python
# web
cd tracemind/web && npm ci && npm run build
# stack
docker compose up -d --build
scripts/prepare_demo_repo.sh    # creates .tracemind/demo-repo (the repo TraceMind investigates)
```

Model settings (`MODEL_PROVIDER`, `MODEL_NAME`, `MODEL_BASE_URL`, `MODEL_API_KEY`) are owner-supplied; see `docs/models.md`. To run remediation tests in Docker from the compose backend you need the opt-in overlay `docker-compose.remediation.yml`; read `docs/SECURITY.md` section 3 first. Build the sandbox image with `scripts/build_sandbox_image.sh`.

Demo app: `demo/` has its own requirements (`demo/requirements-dev.txt`, `demo/worker/requirements.txt`). `scripts/test_all.sh` builds a separate `.venv-demo` because the demo pins older OpenTelemetry versions than the backend. `scripts/reproduce_incident.sh` and `scripts/e2e_lifecycle.sh` drive the demo incident.

## Running tests

```bash
scripts/test_all.sh
```

It runs, reporting each section separately: backend tests (`tracemind/backend/tests`, including the real Docker sandbox), the frontend build, demo integration tests without the `injected_bug` marker (using throwaway Postgres and RabbitMQ containers on ports 56432/56672), and the `injected_bug` demo tests, which are expected to FAIL at the baseline commit (that proves the bug reproduces). Set `EXPECT_FIXED=1` to require them to pass against a patched copy. Docker must be running. Backend only:

```bash
cd tracemind/backend && ../../.venv/bin/python -m pytest -q tests --rootdir .
```

Some tests need Docker; `test_live_integration` in `tests/test_models.py` runs only when `MODEL_API_KEY` is set.

## Branches and commits

- Branch names follow `docs/ARCHITECTURE.md` section 9, e.g. `feature/<area>`; open changes against `main`.
- Use conventional commits (`feat(api): ...`, `fix(remediation): ...`, `docs: ...`, `test: ...`; recent history uses `feat(scope):` and `merge:` prefixes).
- No force-push. Run the relevant tests before opening a PR.
- Do not commit `.env`, API keys, `.tracemind/`, `.sandbox/` or `graphify-out/` (all in `.gitignore` except where noted in the file).

## Reporting bugs and security issues

Use the GitHub issue templates in `.github/ISSUE_TEMPLATE`. Include steps to reproduce, commit/version, and logs with secrets removed. For vulnerabilities, follow `docs/SECURITY.md` section 5 and do not post exploit details publicly.
