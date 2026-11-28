#!/usr/bin/env bash
# Point the phone CRM at the deployed edge Worker.
#
#   EDGE_URL=https://edge-mcp.<sub>.workers.dev EDGE_TOKEN=... bash scripts/phone-edge-env.sh
#
# The running service reads BRIDGE_ENV_FILE, whose default is ~/gowa-espo/.env — NOT
# ~/crm/crm.env (that file is the installer template). Writing to the wrong one looks like
# "edge is not configured" forever, so this script writes to the file the process actually
# loads, keeps it at 0600, restarts the service and proves the result.
set -euo pipefail

: "${EDGE_URL:?set EDGE_URL}"
: "${EDGE_TOKEN:?set EDGE_TOKEN}"

ENV_FILE="${BRIDGE_ENV_FILE:-$HOME/gowa-espo/.env}"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }

tmp="$(mktemp)"
grep -v '^EDGE_URL=\|^EDGE_TOKEN=' "$ENV_FILE" > "$tmp" || true
printf 'EDGE_URL=%s\nEDGE_TOKEN=%s\n' "$EDGE_URL" "$EDGE_TOKEN" >> "$tmp"
cat "$tmp" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
rm -f "$tmp"

command -v sv >/dev/null && sv restart crm >/dev/null 2>&1 || true
sleep 5

echo "env file : $ENV_FILE"
echo "health   : $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8085/health)"
echo "edge     : $(curl -s -m 10 "$EDGE_URL/health" || echo unreachable)"
