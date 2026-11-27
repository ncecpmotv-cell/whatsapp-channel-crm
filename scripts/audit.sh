#!/usr/bin/env bash
# Repeatable audit for the phone CRM: static checks, tests, security probes, HTTP headers.
#
#   bash scripts/audit.sh                 # full run (unit + e2e + HTTP)
#   BASE=http://127.0.0.1:8086 bash scripts/audit.sh
#   SKIP_E2E=1 bash scripts/audit.sh      # faster loop while editing
#
# Reads the token from $BRIDGE_TOKEN or ../var/node.env; never prints it.
set -u
cd "$(dirname "$0")/.." || exit 1
BASE="${BASE:-http://127.0.0.1:8085}"
TOKEN="${BRIDGE_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f var/node.env ]; then
  TOKEN=$(grep -m1 '^BRIDGE_TOKEN=' var/node.env | cut -d= -f2-)
fi
AUTH=$(printf 'crm:%s' "$TOKEN" | base64 -w0)
pass=0; fail=0
ok()   { printf 'PASS  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf 'FAIL  %s\n' "$1"; fail=$((fail+1)); }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

echo "== 1. syntax =="
python3 -m compileall -q bridge scripts >/dev/null 2>&1
check "python compiles" "$([ $? -eq 0 ] && echo 1 || echo 0)"

echo "== 2. unit tests =="
python3 -m unittest discover -s bridge/tests >/tmp/audit-unit.log 2>&1
check "unit tests ($(grep -oE 'Ran [0-9]+ tests' /tmp/audit-unit.log | head -1))" "$([ $? -eq 0 ] && echo 1 || echo 0)"

if [ "${SKIP_E2E:-0}" != "1" ]; then
  echo "== 3. end-to-end =="
  timeout 240 python3 scripts/e2e_local.py >/tmp/audit-e2e.log 2>&1
  check "e2e ($(grep -oE '[0-9]+/[0-9]+ checks passed' /tmp/audit-e2e.log | tail -1))" "$([ $? -eq 0 ] && echo 1 || echo 0)"
fi

echo "== 4. secrets / risky patterns =="
# literal assignments only: reads from env files are fine
secrets=$(grep -rInE '(token|password|secret)[[:space:]]*=[[:space:]]*"[A-Za-z0-9_-]{16,}"' bridge/*.py 2>/dev/null | head -5)
check "no hardcoded credentials" "$([ -z "$secrets" ] && echo 1 || echo 0)"
# \bexec( also matches our DB helper _exec(, so require it not preceded by a word char
risky=$(grep -rnP '(?<![_A-Za-z0-9])eval\(|(?<![_A-Za-z0-9])exec\(|os\.system|shell=True|pickle\.loads' bridge/*.py 2>/dev/null | head -3)
check "no eval/exec/shell=True" "$([ -z "$risky" ] && echo 1 || echo 0)"

echo "== 5. HTTP (needs a reachable instance) =="
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/health" 2>/dev/null)
if [ "$code" != "200" ]; then
  echo "SKIP  http checks ($BASE unreachable, code=$code)"
else
  check "health is public" 1
  st=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/status")
  check "status requires token ($st)" "$([ "$st" = "401" ] && echo 1 || echo 0)"
  st=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -H "Authorization: Bearer $TOKEN" "$BASE/status")
  check "status accepts token ($st)" "$([ "$st" = "200" ] && echo 1 || echo 0)"
  st=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/ui")
  check "ui requires auth ($st)" "$([ "$st" = "401" ] && echo 1 || echo 0)"
  st=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/ui?token=leak")
  check "token query string rejected ($st)" "$([ "$st" = "401" ] && echo 1 || echo 0)"
  html=$(curl -s -m 5 -u "crm:$TOKEN" "$BASE/ui")
  check "csp header present" "$(printf '%s' "$html" >/dev/null; curl -s -D- -o /dev/null -m 5 -u "crm:$TOKEN" "$BASE/ui" | grep -qi 'content-security-policy' && echo 1 || echo 0)"
  check "no inline scripts" "$(printf '%s' "$html" | grep -q '<script>' && echo 0 || echo 1)"
  check "asset urls carry a version" "$(printf '%s' "$html" | grep -qE 'app\.(css|js)\?v=[a-f0-9]{6,}' && echo 1 || echo 0)"
  for asset in app.css app.js pico.min.css; do
    ac=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -u "crm:$TOKEN" "$BASE/static/$asset")
    check "static $asset ($ac)" "$([ "$ac" = "200" ] && echo 1 || echo 0)"
  done
  mn=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/ui/media/aaaaaaaaaaaa.png")
  check "media requires auth ($mn)" "$([ "$mn" = "401" ] && echo 1 || echo 0)"
  mt=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -u "crm:$TOKEN" "$BASE/ui/media/../../etc/passwd")
  check "media traversal blocked ($mt)" "$([ "$mt" = "404" ] && echo 1 || echo 0)"
  check "cross-site POST rejected" "$([ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 -u "crm:$TOKEN" -H 'Sec-Fetch-Site: cross-site' -d 'id=x' "$BASE/ui/content/cancel")" = "403" ] && echo 1 || echo 0)"
fi

echo
echo "== summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
