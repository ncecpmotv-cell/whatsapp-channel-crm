#!/data/data/com.termux/files/usr/bin/bash
# ---------------------------------------------------------------------------
# Upgrade the phone from "GOWA <-> EspoCRM bridge" to "local CRM + GOWA".
# Runs ON the phone, from the git checkout. Idempotent; backs up first.
#
#   bash scripts/upgrade-to-crm.sh                  # switch the bridge only
#   bash scripts/upgrade-to-crm.sh --retire-espocrm # also stop EspoCRM/MariaDB/nginx
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TERMUX_HOME="${HOME:-/data/data/com.termux/files/home}"
BASE="$TERMUX_HOME/gowa-espo"
LIVE="$BASE/bridge"
ENVF="$BASE/.env"
STAMP="$(date +%Y%m%d-%H%M%S)"
RETIRE=0
NO_START=0
DELETE_ESPO=0
for arg in "$@"; do
  [ "$arg" = "--retire-espocrm" ] && RETIRE=1
  [ "$arg" = "--delete-espocrm" ] && { RETIRE=1; DELETE_ESPO=1; }
  [ "$arg" = "--no-start" ] && NO_START=1
done

echo "== before =="
free -m | head -2

echo "== backup =="
[ -d "$LIVE" ] && cp -r "$LIVE" "$BASE/bridge.bak.$STAMP"
[ -f "$ENVF" ] && cp "$ENVF" "$BASE/env.bak.$STAMP"
echo "backup: $BASE/bridge.bak.$STAMP"

echo "== copy bridge =="
mkdir -p "$LIVE"
cp "$REPO"/bridge/*.py "$LIVE"/
mkdir -p "$LIVE/tests" && cp "$REPO"/bridge/tests/*.py "$LIVE/tests"/ 2>/dev/null || true
# EspoCRM client is no longer imported; remove the stale module if present.
rm -f "$LIVE/espocrm.py"

echo "== migrate .env =="
mkdir -p "$BASE/var"
grep -q '^CRM_DB_PATH=' "$ENVF" 2>/dev/null || \
  echo "CRM_DB_PATH=$BASE/var/crm.db" >> "$ENVF"
grep -q '^AGENT_CAN_PUBLISH=' "$ENVF" 2>/dev/null || echo "AGENT_CAN_PUBLISH=0" >> "$ENVF"
grep -q '^DAILY_PUBLISH_CAP=' "$ENVF" 2>/dev/null || echo "DAILY_PUBLISH_CAP=30" >> "$ENVF"
chmod 600 "$ENVF"

if [ "$RETIRE" = "1" ]; then
  echo "== retire EspoCRM stack (files kept) =="
  for svc in espocrm nginx mariadb; do
    sv down "$svc" 2>/dev/null && echo "stopped: $svc" || echo "not running: $svc"
  done
fi

if [ "$DELETE_ESPO" = "1" ]; then
  echo "== permanent delete: EspoCRM + MariaDB (+ nginx config) =="
  mkdir -p "$BASE/var"
  DUMP="$BASE/var/espocrm-dump-$(date +%Y%m%d-%H%M).sql.gz"
  if command -v mysqldump >/dev/null 2>&1 || command -v mariadb-dump >/dev/null 2>&1; then
    DUMPBIN="$(command -v mariadb-dump || command -v mysqldump)"
    if "$DUMPBIN" -u root espocrm 2>/dev/null | gzip > "$DUMP" && [ -s "$DUMP" ]; then
      echo "db dump kept at $DUMP"
    else
      echo "WARNING: dump failed — nothing deleted"
      exit 1
    fi
  else
    echo "no dump tool found; copying the raw datadir instead"
    tar czf "$BASE/var/mariadb-datadir-$(date +%Y%m%d-%H%M).tar.gz" \
      -C "${PREFIX:-/data/data/com.termux/files/usr}/var/lib" mysql 2>/dev/null || true
  fi
  for svc in espocrm nginx mariadb; do sv down "$svc" 2>/dev/null || true; done
  sleep 1
  ESPO_DIR="${ESPO_DIR:-$TERMUX_HOME/espocrm}"
  [ -d "$TERMUX_HOME/sanad/espocrm" ] && ESPO_DIR="$TERMUX_HOME/sanad/espocrm"
  rm -rf "$ESPO_DIR" "$TERMUX_HOME/sanad/espocrm" "$TERMUX_HOME/espocrm"
  rm -rf "${PREFIX:-/data/data/com.termux/files/usr}/var/service/espocrm" \
         "${PREFIX:-/data/data/com.termux/files/usr}/var/service/nginx" \
         "${PREFIX:-/data/data/com.termux/files/usr}/var/service/mariadb"
  rm -rf "${PREFIX:-/data/data/com.termux/files/usr}/var/lib/mysql"
  rm -f "${PREFIX:-/data/data/com.termux/files/usr}/etc/my.cnf.d/zz-low-ram.cnf"
  ( crontab -l 2>/dev/null | grep -v 'espocrm/cron.php' ) | crontab - 2>/dev/null || true
  echo "deleted. kept: $DUMP (delete it yourself once you are sure)"
fi

if [ "$NO_START" = "1" ]; then
  echo "== skip restart (--no-start) =="
  ls "$LIVE" | tr '\n' ' '; echo
  grep -E '^(CRM_DB_PATH|AGENT_CAN_PUBLISH|DAILY_PUBLISH_CAP)=' "$ENVF"
  exit 0
fi

echo "== restart bridge =="
sv restart bridge 2>/dev/null || {
  pkill -f 'gowa-espo/bridge/app.py' 2>/dev/null || true
  sleep 1
  cd "$LIVE" && nohup python3 "$LIVE/app.py" >>"$BASE/var/bridge.log" 2>&1 </dev/null &
  disown 2>/dev/null || true
}
sleep 3

echo "== tailscale node =="
if command -v tailscale >/dev/null 2>&1; then
  tailscale serve --bg --https=8444 "http://127.0.0.1:${BRIDGE_PORT}" 2>&1 | tail -3 \
    || echo "tailscale serve failed (is Tailscale up and HTTPS enabled?)"
  tailscale serve status 2>/dev/null | head -6
else
  echo "tailscale CLI not found; skipping"
fi

echo "== verify =="
TOKEN="$(grep '^BRIDGE_TOKEN=' "$ENVF" | cut -d= -f2-)"
curl -s -m 5 http://127.0.0.1:8085/health || echo "health failed"
echo
curl -s -o /dev/null -w 'UI=%{http_code}\n' -m 5 -u "crm:$TOKEN" http://127.0.0.1:8085/ui
curl -s -m 5 -X POST http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 200
echo

echo "== after =="
free -m | head -2
echo "done. rollback: cp -r $BASE/bridge.bak.$STAMP/* $LIVE/ && sv restart bridge"
