#!/usr/bin/env bash
# End-to-end lifecycle: fault-injected notification -> duplicate -> OTLP -> incident -> investigation -> remediation.
# Needs: docker compose stack up WITH docker-compose.remediation.yml, a working MODEL_* config in .env,
#        scripts/prepare_demo_repo.sh and scripts/build_sandbox_image.sh already run, TRACEMIND_HOST_ROOT set.
# Real model calls are made (several minutes, uses your API quota). Exits non-zero on the first failed assertion.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
TM="${TM_URL:-http://localhost:8100}"
REPO="${TRACEMIND_DEMO_REPO:-$ROOT/.tracemind/demo-repo}"
j() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
tree_hash() { find "$REPO" -path '*/.git' -prune -o -type f -print0 | sort -z | xargs -0 shasum | shasum | cut -c1-16; }
poll() { # poll <url> <python-expr-true-when-done> <timeout-seconds>
  local end=$((SECONDS+$3)); while (( SECONDS < end )); do
    curl -s "$1" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if ($2) else 1)" && return 0; sleep 5; done; echo "TIMEOUT waiting on $1"; return 1; }

echo "== 1. trigger the deterministic failure and confirm the duplicate"
"$ROOT/scripts/reproduce_incident.sh" | tee /dev/stderr | grep -q "DUPLICATE REPRODUCED"
sleep 8                                            # let the collector batch reach TraceMind

echo "== 2. detect incident from ingested telemetry"
BEFORE=$(curl -s "$TM/api/incidents" | j "' '.join(i['id'] for i in d['incidents'])")
curl -s -XPOST "$TM/api/incidents/detect" >/dev/null
INC=$(curl -s "$TM/api/incidents" | BEFORE="$BEFORE" python3 -c "
import json,sys,os; b=set(os.environ['BEFORE'].split()); d=json.load(sys.stdin)['incidents']
new=[i['id'] for i in d if i['id'] not in b]; print((new or [d[0]['id']])[0])")
echo "incident: $INC"

echo "== 3. register the repository TraceMind investigates"
curl -s -XPOST "$TM/api/repositories" -H 'content-type: application/json' -d "{\"path\":\"$REPO\",\"name\":\"demo-notifications\"}" | j "'repo '+d['id']+' @ '+d['commit_sha'][:8]"

echo "== 4. investigate (live model)"
INV=$(curl -s -XPOST "$TM/api/incidents/$INC/investigations" -H 'content-type: application/json' -d '{}' | j "d['investigation_id']")
poll "$TM/api/investigations/$INV" "d['status'] in ('completed','failed')" 900
curl -s "$TM/api/investigations/$INV" | python3 -c "
import json,sys; d=json.load(sys.stdin); a=d['adjudication']
assert d['status']=='completed', d['error']
print('code backend:', d['code_backend'], '| certainty:', a['certainty'], '| winner:', a['winning_hypothesis_id'])
for h in d['hypotheses']: print(' ', h['id'], h['validation_status'], 'code refs:', [r for r in h['supporting_refs'] if r.startswith('code:')])
assert a['certainty'] in ('confirmed','suspected'), 'investigation inconclusive'"

echo "== 5. remediate (live model patch -> isolated copy -> Docker sandbox)"
H0=$(tree_hash)
REM=$(curl -s -XPOST "$TM/api/investigations/$INV/remediations" -H 'content-type: application/json' -d '{}' | j "d['remediation_id']")
poll "$TM/api/remediations/$REM" "d['status'] in ('verified','tested','failed')" 900
curl -s "$TM/api/remediations/$REM" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('status:', d['status'], '| error:', d['error'])
for t in d['test_results']: print('  test', t['phase'], t['outcome'], t['name'])
for c in d['command_runs']: print('  cmd ', c['phase'], 'exit', c['exit_code'])
print(d['diff'])
assert d['status']=='verified', 'NOT verified'"

echo "== 6. source repository unchanged"
[ "$H0" = "$(tree_hash)" ] && [ -z "$(git -C "$REPO" status --porcelain)" ] && echo "source repo untouched (hash $H0)"
echo "LIFECYCLE OK: incident=$INC investigation=$INV remediation=$REM"
