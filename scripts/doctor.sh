#!/usr/bin/env bash
# Everything the system needs, checked in one pass. Read-only: it never fixes anything.
#
#   bash scripts/doctor.sh            # check this machine
#   CRM_HOME=~/crm bash scripts/doctor.sh
#
# Exit code: 0 when every required check passes, 1 otherwise.
set -uo pipefail

GOWA_PORT="${GOWA_PORT:-3000}"
BRIDGE_PORT="${BRIDGE_PORT:-8085}"
PICO_PORT="${PICO_PORT:-18790}"

pass=0; fail=0; warn=0
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; pass=$((pass+1)); }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; fail=$((fail+1)); }
meh()  { printf '  \033[1;33m!\033[0m %s\n' "$*"; warn=$((warn+1)); }
head_() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }

# ---- layout --------------------------------------------------------------
SVDIR="${SVDIR:-${PREFIX:-}/var/service}"
if [ -d "$SVDIR/crm" ]; then
  LAYOUT="runit"
  ROOT="${CRM_HOME:-$HOME/crm}"
  ENVF="${CRM_ENV:-$HOME/crm/crm.env}"
  [ -f "$ENVF" ] || ENVF="$HOME/gowa-espo/.env"
  BIN="${CRM_BIN:-$HOME/gowa-espo/bin}"
else
  LAYOUT="installer"
  ROOT="${CRM_HOME:-$HOME/.whatsapp-crm}"
  ENVF="$ROOT/etc/crm.env"
  BIN="$ROOT/bin"
fi

read_env() {  # key -> value from the env file without exporting secrets
  [ -f "$ENVF" ] || return 1
  sed -n "s/^$1=//p" "$ENVF" | head -1 | sed 's/^["'\'']//;s/["'\'']$//'
}

http() { curl -s -o /dev/null -w '%{http_code}' -m 5 "$@" 2>/dev/null; }

head_ "Layout: $LAYOUT  ·  root: $ROOT"

# ---- toolchain -----------------------------------------------------------
head_ "Toolchain"
for c in python3 curl; do
  command -v "$c" >/dev/null 2>&1 && ok "$c $(command -v $c)" || bad "$c missing"
done
GOWA_BIN=""
for c in "$BIN/gowa" "$BIN/whatsapp" "$(command -v gowa 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && { GOWA_BIN="$c"; break; }
done
[ -n "$GOWA_BIN" ] && ok "gowa  $GOWA_BIN" || bad "gowa binary not found (looked in $BIN)"

PICO_BIN=""
for c in "$BIN/picoclaw" "$ROOT/picoclaw/picoclaw" "$HOME/pico/bin/picoclaw" \
         "$(command -v picoclaw 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && { PICO_BIN="$c"; break; }
done
[ -n "$PICO_BIN" ] && ok "picoclaw  $PICO_BIN" || bad "picoclaw binary not found"

[ -x "$BIN/tailscale" ] && ok "tailscale  $BIN/tailscale" \
  || meh "tailscale not in $BIN (system: $(command -v tailscale || echo none))"

# ---- services ------------------------------------------------------------
head_ "Services"
if [ "$LAYOUT" = "runit" ]; then
  for s in gowa crm picoclaw; do
    if sv status "$SVDIR/$s" 2>/dev/null | grep -q '^run:'; then ok "$s running"; else bad "$s down"; fi
  done
  for s in sshd tailscaled; do
    sv status "$SVDIR/$s" 2>/dev/null | grep -q '^run:' && ok "$s running" || meh "$s not running"
  done
else
  "$BIN/crmctl" status >/dev/null 2>&1 && ok "crmctl reports the stack up" || bad "crmctl status failed"
fi

# ---- ports + health ------------------------------------------------------
head_ "Endpoints"
code="$(http "http://127.0.0.1:$BRIDGE_PORT/health")"
[ "$code" = "200" ] && ok "CRM  :$BRIDGE_PORT/health" || bad "CRM  :$BRIDGE_PORT → $code"
code="$(http "http://127.0.0.1:$GOWA_PORT/health")"
[ "$code" = "200" ] && ok "GOWA :$GOWA_PORT/health" || bad "GOWA :$GOWA_PORT → $code"
code="$(http "http://127.0.0.1:$PICO_PORT/health")"
[ "$code" = "200" ] && ok "Pico :$PICO_PORT/health" || bad "Pico :$PICO_PORT → $code"

# ---- whatsapp session ----------------------------------------------------
head_ "WhatsApp"
u="$(read_env GOWA_USER)"; p="$(read_env GOWA_PASSWORD)"
if [ -n "$u" ] && [ -n "$p" ]; then
  st="$(curl -s -m 6 -u "$u:$p" -H 'X-Device-Id: primary' \
        "http://127.0.0.1:$GOWA_PORT/app/status" 2>/dev/null)"
  if echo "$st" | grep -q '"is_logged_in": *true'; then
    ok "device paired"
  else
    bad "not paired — run: bash scripts/install.sh --qr"
  fi
else
  meh "GOWA_USER/PASSWORD not found in $ENVF"
fi

# ---- CRM internals -------------------------------------------------------
head_ "CRM"
tok="$(read_env BRIDGE_TOKEN)"
if [ -n "$tok" ]; then
  tools="$(curl -s -m 8 -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' "http://127.0.0.1:$BRIDGE_PORT/mcp" \
    | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["result"]["tools"]))' 2>/dev/null)"
  [ "${tools:-0}" -ge 16 ] && ok "MCP tools: $tools" || bad "MCP tools: ${tools:-0} (expected 16)"
  ui="$(http -u "crm:$tok" "http://127.0.0.1:$BRIDGE_PORT/ui")"
  [ "$ui" = "200" ] && ok "UI answers with the token" || bad "UI → $ui"
else
  meh "BRIDGE_TOKEN not found in $ENVF"
fi

# ---- agent ---------------------------------------------------------------
head_ "Agent"
if [ -n "$PICO_BIN" ]; then
  pico_home="$ROOT/picoclaw"
  [ -d "$pico_home" ] || pico_home="$HOME/pico"
  skills="$(PICOCLAW_HOME="$pico_home" "$PICO_BIN" skills list 2>/dev/null | grep -c '✓')"
  [ "${skills:-0}" -ge 1 ] && ok "skills installed: $skills" || meh "no skills found in $pico_home"
  grep -q '"crm"' "$pico_home/config.json" 2>/dev/null \
    && ok "MCP server 'crm' registered" || bad "MCP server 'crm' missing from $pico_home/config.json"
fi

# ---- tailnet -------------------------------------------------------------
head_ "Tailscale"
sock="$ROOT/var/tailscaled.sock"
[ -f "$sock" ] || sock="${HOME}/gowa-espo/var/tailscaled.sock"
if [ -x "$BIN/tailscale" ] || command -v tailscale >/dev/null 2>&1; then
  TS="$BIN/tailscale"; [ -x "$TS" ] || TS="$(command -v tailscale)"
  # On Android the static Go binary needs proot for the Go resolver (SIGSYS otherwise).
  TS_RUN=("$TS")
  if command -v proot >/dev/null 2>&1 && [ -f "$HOME/gowa-espo/etc/resolv.conf" ]; then
    TS_RUN=(proot -b "$HOME/gowa-espo/etc/resolv.conf:/etc/resolv.conf" \
            -b "${PREFIX:-/usr}/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt" "$TS")
  fi
  st="$("${TS_RUN[@]}" --socket="$sock" status 2>&1 | head -1)"
  if [ -z "$st" ]; then
    meh "tailscale status unavailable (socket: $sock)"
  elif printf '%s' "$st" | grep -q "Logged out"; then
    bad "tailscale logged out — open the login link, then: bash scripts/install.sh --finish"
  else
    ok "node: ${st%% *}"
  fi
  serve_status="$("${TS_RUN[@]}" --socket="$sock" serve status 2>/dev/null)"
  if printf '%s' "$serve_status" | grep -q 'https://'; then
    ok "$(printf '%s' "$serve_status" | grep -m1 'https://' | awk '{print $1}')"
  else
    meh "no https serve config — bash scripts/install.sh --finish"
  fi
else
  meh "tailscale binary not found"
fi

# ---- push ----------------------------------------------------------------
head_ "Push notifications"
command -v termux-notification >/dev/null 2>&1 && ok "termux-api present" || meh "termux-api missing (pkg install termux-api)"
if [ -n "$tok" ]; then
  ph="$(curl -s -m 6 "http://127.0.0.1:$BRIDGE_PORT/health")"
  if printf '%s' "$ph" | grep -qE '"enabled": *true'; then
    ok "push enabled"
  else
    meh "push disabled (set TELEGRAM_* or install termux-api)"
  fi
fi

# ---- summary -------------------------------------------------------------
printf '\n\033[1m%d passed · %d failed · %d warnings\033[0m\n' "$pass" "$fail" "$warn"
[ "$fail" -eq 0 ] || exit 1
