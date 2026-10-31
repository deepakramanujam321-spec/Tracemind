#!/usr/bin/env bash
# Build the remediation sandbox image (tracemind-sandbox:latest). This is the ONLY networked step; tests run offline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$ROOT/tracemind/backend/tracemind/remediation/sandbox"
docker build -t tracemind-sandbox:latest -f "$D/Dockerfile.sandbox" "$D"
