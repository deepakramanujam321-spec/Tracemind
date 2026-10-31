#!/usr/bin/env bash
# Run every suite with the correct polarity for the injected bug. Needs Docker (throwaway Postgres/RabbitMQ for the
# demo integration tests are started on non-default ports and removed afterwards). Reports each suite separately.
#   - backend + investigation + sandbox tests: must all pass
#   - demo tests WITHOUT the injected_bug marker: must pass
#   - demo tests WITH the injected_bug marker: must FAIL at the baseline commit (proves the bug reproduces);
#     after a remediation they must pass (run with EXPECT_FIXED=1 against the patched copy)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="$ROOT/.venv/bin/python"; DPY="$ROOT/.venv-demo/bin/python"; fail=0
if [ ! -x "$DPY" ]; then  # separate venv: demo pins older OpenTelemetry versions than the backend
  python3 -m venv "$ROOT/.venv-demo" && "$DPY" -m pip install -q -r demo/requirements-dev.txt -r demo/worker/requirements.txt 'setuptools<81'
fi
section() { printf '\n=== %s ===\n' "$1"; }
section "backend (ingest, store, correlation, investigation, models, code, remediation incl. real Docker sandbox)"
(cd tracemind/backend && "$PY" -m pytest -q tests --rootdir .) || fail=1
section "frontend build"
(cd tracemind/web && npm ci --silent && npm run build 2>&1 | tail -3) || fail=1
section "demo integration (non-bug tests; throwaway Postgres + RabbitMQ)"
PG=tm-test-demo-pg-$$; MQ=tm-test-demo-mq-$$
docker run -d --rm --name $PG -e POSTGRES_PASSWORD=t -e POSTGRES_USER=tracemind -e POSTGRES_DB=app -p 56432:5432 postgres:16 >/dev/null
docker run -d --rm --name $MQ -p 56672:5672 rabbitmq:3.13 >/dev/null
trap 'docker rm -f $PG $MQ >/dev/null 2>&1' EXIT
for _ in $(seq 1 60); do docker exec $PG pg_isready -U tracemind >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do docker exec $MQ rabbitmq-diagnostics -q ping >/dev/null 2>&1 && break; sleep 1; done
export APP_DATABASE_URL=postgresql://tracemind:t@localhost:56432/app RABBITMQ_URL=amqp://guest:guest@localhost:56672/
(cd demo && "$DPY" -m pytest -q tests -m "not injected_bug" ) || fail=1
section "injected-bug specs (demo/tests, integration + offline sandbox variant)"
if [ "${EXPECT_FIXED:-0}" = 1 ]; then
  (cd demo && "$DPY" -m pytest -q tests -m injected_bug) || fail=1
else
  (cd demo && "$DPY" -m pytest -q tests -m injected_bug >/tmp/injected.out 2>&1); rc=$?
  tail -4 /tmp/injected.out
  if [ $rc -eq 0 ]; then echo "UNEXPECTED: injected_bug specs pass at baseline (bug not present?)"; fail=1
  else echo "OK: injected_bug specs FAIL at baseline, as designed (reproduces the duplicate)"; fi
fi
exit $fail
