#!/usr/bin/env bash
# Create the standalone git repository TraceMind investigates: a snapshot of demo/ at the current HEAD,
# so TraceMind treats the demo as an external project (it never edits it; remediation works on a copy).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/.tracemind/demo-repo}"
# Refresh contents IN PLACE (do not rm -rf the directory): a running container that bind-mounts it would be left
# pointing at a deleted inode.
mkdir -p "$DEST"; find "$DEST" -mindepth 1 -delete
git -C "$ROOT" archive HEAD demo | tar -x -C "$DEST" --strip-components=1
cd "$DEST"
git init -q -b main
git -c user.name=tracemind -c user.email=tracemind@example.invalid add -A
git -c user.name=tracemind -c user.email=tracemind@example.invalid commit -q -m "demo app snapshot (baseline with injected bug)"
echo "demo repo ready: $DEST ($(git rev-parse --short HEAD))"
