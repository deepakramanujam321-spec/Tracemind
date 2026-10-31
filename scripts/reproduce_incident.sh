#!/usr/bin/env bash
# Reproduces the demo incident: ONE notification sent with fault=ack_failure ends up as TWO inbox rows
# (worker commits, fails before ack, RabbitMQ redelivers, plain INSERT duplicates it).
set -euo pipefail
API="${API_URL:-http://localhost:8000}"
USER_ID="${USER_ID:-u-1}"
echo ">> POST one notification with fault=ack_failure"
RESP=$(curl -fsS -X POST "$API/api/notifications" -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$USER_ID\",\"title\":\"Welcome\",\"body\":\"Your order shipped\",\"fault\":\"ack_failure\"}")
echo "$RESP"
sleep "${WAIT_SECONDS:-4}"
echo ">> Inbox for $USER_ID"
INBOX=$(curl -fsS "$API/api/notifications?user_id=$USER_ID")
if command -v python3 >/dev/null; then
  echo "$INBOX" | python3 -c 'import json,sys
rows=json.load(sys.stdin)
for r in rows: print(r["id"], r["notification_id"], r["title"], r["status"], r["created_at"])
ids={r["notification_id"] for r in rows}
print(f"rows={len(rows)} distinct_notification_ids={len(ids)}")
print("DUPLICATE REPRODUCED" if len(rows)>len(ids) else "no duplicate")'
else
  echo "$INBOX"
fi
