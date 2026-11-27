#!/usr/bin/env bash
# One-shot installer for the WhatsApp Channel CRM stack:
#   GOWA (WhatsApp gateway) + CRM bridge (UI + MCP) + PicoClaw (agent)
#
#   bash scripts/install.sh                 # fresh install into ~/.whatsapp-crm
#   bash scripts/install.sh --upgrade       # pull the latest GOWA / PicoClaw / CRM
#   bash scripts/install.sh --qr            # show the WhatsApp pairing QR
#   bash scripts/install.sh --prefix DIR    # install somewhere else
#   bash scripts/install.sh --dry-run       # print the plan, touch nothing
#
# Tested on Termux (aarch64) and Debian/Ubuntu (amd64, arm64).
set -euo pipefail

REPO_URL="${CRM_REPO:-https://github.com/ncecpmotv-cell/whatsapp-channel-crm}"
ROOT="${CRM_HOME:-$HOME/.whatsapp-crm}"
GOWA_PORT="${GOWA_PORT:-3000}"
BRIDGE_PORT="${BRIDGE_PORT:-8085}"
PICO_PORT="${PICO_PORT:-18790}"
MODE="install"
DRY=0
SKIP_GOWA=0
SKIP_PICO=0
SKIP_TAILSCALE=0
NO_SERVICE=0
LOCAL_SRC=""

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then printf '   would run: %s\n' "$*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --upgrade) MODE="upgrade"; shift ;;
    --qr) MODE="qr"; shift ;;
    --prefix) ROOT="$2"; shift 2 ;;
    --port) BRIDGE_PORT="$2"; shift 2 ;;
    --skip-gowa) SKIP_GOWA=1; shift ;;
    --skip-picoclaw) SKIP_PICO=1; shift ;;
    --no-service) NO_SERVICE=1; shift ;;
    --from-local) LOCAL_SRC="$2"; shift 2 ;;
    --skip-tailscale) SKIP_TAILSCALE=1; shift ;;
    --tailscale) MODE="tailscale"; shift ;;
    --finish) MODE="finish"; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

BIN="$ROOT/bin"
ETC="$ROOT/etc"
VAR="$ROOT/var"
LOG="$VAR/log"

is_termux() { [ -n "${PREFIX:-}" ] && [ -d "${PREFIX:-}/bin" ] && uname -o 2>/dev/null | grep -qi android; }
arch() {
  case "$(uname -m)" in
    aarch64|arm64) echo arm64 ;;
    armv7l|armv7)  echo armv7 ;;
    armv6l|armv6)  echo armv6 ;;
    x86_64|amd64)  echo amd64 ;;
    *) die "unsupported architecture: $(uname -m)" ;;
  esac
}
pico_arch() { [ "$(arch)" = "amd64" ] && echo x86_64 || arch; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing '$1' — install it first"; }

install_deps() {
  if is_termux; then
    say "Installing Termux packages"
    run pkg install -y python curl unzip tar openssl-tool proot
    # Optional but recommended: on-screen notifications (needs the Termux:API app)
    command -v termux-notification >/dev/null 2>&1 || \
      warn "termux-api not installed: pkg install termux-api + the Termux:API app (push notifications)"
  else
    need python3; need curl; need unzip; need tar
  fi
}

ts_arch() {
  case "$(uname -m)" in
    aarch64|arm64) echo arm64 ;;
    x86_64|amd64)  echo amd64 ;;
    armv7l|armv7)  echo arm ;;
    armv6l|armv6)  echo arm ;;
    *) die "tailscale: unsupported architecture $(uname -m)" ;;
  esac
}

install_tailscale() {
  [ -x "$BIN/tailscale" ] && { say "tailscale already in $BIN"; return 0; }
  if command -v tailscale >/dev/null 2>&1; then
    say "using the system tailscale"
    return 0
  fi
  local tarball tmp
  tarball="$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['Tarballs']['$(ts_arch)'])")" || return 1
  say "tailscale $tarball"
  tmp="$(mktemp -d)"
  run curl -fsSL "https://pkgs.tailscale.com/stable/$tarball" -o "$tmp/ts.tgz"
  if [ "$DRY" = 0 ]; then
    tar xzf "$tmp/ts.tgz" -C "$tmp"
    install -m 0755 "$(find "$tmp" -type f -name tailscale  | head -1)" "$BIN/tailscale"
    install -m 0755 "$(find "$tmp" -type f -name tailscaled | head -1)" "$BIN/tailscaled"
  fi
  rm -rf "$tmp"
}

tailscale_unit() {  # runit on Termux; instructions elsewhere
  local sock="$VAR/tailscaled.sock" state="$VAR/tailscaled.state" dir="$VAR/tailscale-state"
  mkdir -p "$VAR" "$dir" 2>/dev/null || true
  if ! is_termux; then
    warn "not Termux: run tailscaled yourself, e.g."
    printf '    tailscaled --tun=userspace-networking --statedir=%s --state=%s --socket=%s\n' \
      "$dir" "$state" "$sock"
    return 0
  fi
  [ -f "$ROOT/etc/resolv.conf" ] || printf 'nameserver 1.1.1.1\n' > "$ROOT/etc/resolv.conf"
  local svc="$PREFIX/var/service/tailscaled"
  run mkdir -p "$svc" "$svc/log" "$PREFIX/var/log/sv/tailscaled"
  if [ "$DRY" = 0 ]; then
    cat > "$svc/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
exec 2>&1
HOME=\$HOME
export SSL_CERT_FILE="\${SSL_CERT_FILE:-\$PREFIX/etc/tls/cert.pem}"
export SSL_CERT_DIR="\${SSL_CERT_DIR:-\$PREFIX/etc/tls}"
exec proot -b "$ROOT/etc/resolv.conf:/etc/resolv.conf" \\
  -b "\$PREFIX/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt" \\
  "$BIN/tailscaled" \\
  --tun=userspace-networking \\
  --state="$state" --statedir="$dir" --socket="$sock" --port=41641
EOF
    printf '#!/data/data/com.termux/files/usr/bin/sh\nexec svlogd -tt %s/var/log/sv/tailscaled\n' \
      "$PREFIX" > "$svc/log/run"
    chmod +x "$svc/run" "$svc/log/run"
    ( command -v service-daemon >/dev/null 2>&1 && service-daemon start ) >/dev/null 2>&1 || true
    sv up tailscaled 2>/dev/null || true
  fi
  say "tailscaled unit: $svc (userspace networking, state in $VAR)"
}

tailscale_login() {
  local sock="$VAR/tailscaled.sock" name log="$LOG/tailscale-login.log"
  name="${TAILSCALE_HOSTNAME:-$(hostname 2>/dev/null || echo crm-phone)}"
  say "Tailscale login (hostname: $name)"
  if [ "$DRY" = 1 ]; then
    printf '   would run: tailscale up --hostname %s --accept-dns=false --accept-routes=false\n' "$name"
    return 0
  fi
  "$BIN/tailscale" --socket="$sock" up --hostname "$name" \
    --accept-dns=false --accept-routes=false >"$log" 2>&1 &
  local url="" i=0
  while [ "$i" -lt 12 ]; do
    url="$(grep -o 'https://login.tailscale.com/a/[a-z0-9]*' "$log" 2>/dev/null | head -1)"
    [ -n "$url" ] && break
    sleep 1; i=$((i + 1))
  done
  if [ -n "$url" ]; then
    printf '\n  Open this link once, then re-run: bash scripts/install.sh --finish\n  %s\n\n' "$url"
  else
    warn "could not read a login URL (see $log); run: $BIN/tailscale --socket=$sock up"
  fi
}

tailscale_serve() {
  local sock="$VAR/tailscaled.sock"
  say "Publishing the UI on the tailnet"
  run "$BIN/tailscale" --socket="$sock" serve --bg --https=443 "http://127.0.0.1:$BRIDGE_PORT"
  [ "$DRY" = 1 ] || "$BIN/tailscale" --socket="$sock" serve status 2>/dev/null | head -4
}

latest_tag() {  # repo -> tag (vX.Y.Z)
  curl -fsSL "https://api.github.com/repos/$1/releases/latest" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])'
}

install_gowa() {
  local tag asset url tmp bin
  tag="$(latest_tag aldinokemal/go-whatsapp-web-multidevice)"
  asset="whatsapp_${tag#v}_linux_$(arch).zip"
  url="https://github.com/aldinokemal/go-whatsapp-web-multidevice/releases/download/$tag/$asset"
  say "GOWA $tag ($asset)"
  tmp="$(mktemp -d)"
  run curl -fsSL "$url" -o "$tmp/gowa.zip"
  if [ "$DRY" = 0 ]; then
    unzip -qo "$tmp/gowa.zip" -d "$tmp/gowa"
    # release zips name the payload after the platform (linux-arm64); older ones "whatsapp"
    bin="$(find "$tmp/gowa" -maxdepth 2 -type f -size +1M ! -iname '*.md' | head -1)"
    [ -n "$bin" ] || die "no binary inside $asset"
    install -m 0755 "$bin" "$BIN/gowa"
  fi
  rm -rf "$tmp"
}

install_picoclaw() {
  local tag asset url tmp found
  tag="$(latest_tag sipeed/picoclaw)"
  asset="picoclaw_Linux_$(pico_arch).tar.gz"
  url="https://github.com/sipeed/picoclaw/releases/download/$tag/$asset"
  say "PicoClaw $tag ($asset)"
  tmp="$(mktemp -d)"
  run curl -fsSL "$url" -o "$tmp/pico.tar.gz"
  if [ "$DRY" = 0 ]; then
    tar -xzf "$tmp/pico.tar.gz" -C "$tmp"
    found="$(find "$tmp" -type f -name picoclaw | head -1)"
    [ -n "$found" ] || die "picoclaw binary not found in $asset"
    install -m 0755 "$found" "$BIN/picoclaw"
  fi
  rm -rf "$tmp"
}

install_crm() {
  say "CRM code -> $ROOT/app"
  if [ -n "$LOCAL_SRC" ]; then
    run mkdir -p "$ROOT/app"
    run cp -R "$LOCAL_SRC/bridge" "$LOCAL_SRC/scripts" "$LOCAL_SRC/picoclaw" \
        "$LOCAL_SRC/README.md" "$ROOT/app/"
  elif [ -d "$ROOT/app/.git" ]; then
    run git -C "$ROOT/app" fetch --depth 1 origin main
    run git -C "$ROOT/app" reset --hard origin/main
  else
    run git clone --depth 1 "$REPO_URL" "$ROOT/app"
  fi
}

rand() { python3 -c 'import secrets;print(secrets.token_urlsafe(24))' 2>/dev/null || openssl rand -base64 24 | tr -d '/+=' ; }

write_configs() {
  local token secret gowa_pass
  if [ -f "$ETC/crm.env" ]; then
    say "Keeping existing secrets in $ETC/crm.env"
    return
  fi
  token="$(rand)"; secret="$(rand)"; gowa_pass="$(rand)"
  say "Writing $ETC/crm.env and $ETC/gowa.env (mode 600)"
  run mkdir -p "$ETC" "$VAR/media" "$VAR/static"
  if [ "$DRY" = 0 ]; then
    cat > "$ETC/crm.env" <<EOF
# generated by scripts/install.sh — keep private
BRIDGE_TOKEN=$token
GOWA_BASE_URL=http://127.0.0.1:$GOWA_PORT
GOWA_USER=crm
GOWA_PASSWORD=$gowa_pass
GOWA_WEBHOOK_SECRET=$secret
BRIDGE_HOST=127.0.0.1
BRIDGE_PORT=$BRIDGE_PORT
CRM_DB_PATH=$VAR/crm.db
MEDIA_DIR=$VAR/media
STATIC_CACHE=$VAR/static
NEWSLETTER_JIDS=
PICO_HOST=127.0.0.1
PICO_PORT=$PICO_PORT
PICO_TOKEN=
AGENT_CAN_PUBLISH=0
DAILY_PUBLISH_CAP=30
TZ_OFFSET=3
EOF
    cat > "$ETC/gowa.env" <<EOF
APP_PORT=$GOWA_PORT
APP_HOST=127.0.0.1
APP_BASIC_AUTH=crm:$gowa_pass
APP_UI_ENABLED=true
APP_DEBUG=false
WHATSAPP_WEBHOOK=http://127.0.0.1:$BRIDGE_PORT/webhook/gowa
WHATSAPP_WEBHOOK_SECRET=$secret
WHATSAPP_WEBHOOK_EVENTS=message
EOF
    chmod 600 "$ETC/crm.env" "$ETC/gowa.env"
  fi
}

setup_pico() {
  [ "$SKIP_PICO" = 1 ] && return
  local home="$ROOT/picoclaw" token
  say "PicoClaw config -> $home/config.json"
  [ "$DRY" = 1 ] && return
  mkdir -p "$home"
  token="$(grep '^BRIDGE_TOKEN=' "$ETC/crm.env" | cut -d= -f2-)"
  PICOCLAW_HOME="$home" bash -c "echo y | '$BIN/picoclaw' config reset" >/dev/null 2>&1 || true
  PICOCLAW_HOME="$home" "$BIN/picoclaw" mcp add crm "http://127.0.0.1:$BRIDGE_PORT/mcp" \
      -t http -H "Authorization: Bearer $token" -f >/dev/null 2>&1 \
      || warn "could not register the CRM as an MCP server; run: PICOCLAW_HOME=$home $BIN/picoclaw mcp add crm ..."
  local skills_src="$ROOT/app/picoclaw/skills"
  if [ -d "$skills_src" ]; then
    mkdir -p "$home/skills"
    cp -R "$skills_src/." "$home/skills/" 2>/dev/null || true
    say "Skills -> $home/skills (content-strategist)"
  fi
  warn "set the model API key: PICOCLAW_HOME=$home $BIN/picoclaw model"
}

write_crmctl() {
  say "Launcher -> $BIN/crmctl"
  [ "$DRY" = 1 ] && return
  cat > "$BIN/crmctl" <<EOF
#!/usr/bin/env bash
set -uo pipefail
ROOT="$ROOT"; LOG="$LOG"; VAR="$VAR"; ETC="$ETC"
GOWA_PORT="$GOWA_PORT"; BRIDGE_PORT="$BRIDGE_PORT"

start() {
  mkdir -p "\$LOG"
  if [ -x "$BIN/gowa" ] && ! pgrep -f "$BIN/gowa" >/dev/null; then
    ( mkdir -p "\$ROOT/gowa"; cd "\$ROOT/gowa"
      set -a; . "\$ETC/gowa.env"; set +a
      nohup "$BIN/gowa" rest >>"\$LOG/gowa.log" 2>&1 & echo \$! >"\$VAR/gowa.pid" )
    echo "gowa  : starting"
  fi
  if ! pgrep -f "\$ROOT/app/bridge/app.py" >/dev/null; then
    ( set -a; . "\$ETC/crm.env"; set +a
      cd "\$ROOT/app/bridge"
      nohup python3 app.py >>"\$LOG/crm.log" 2>&1 & echo \$! >"\$VAR/crm.pid" )
    echo "crm   : starting"
  fi
  if [ -x "$BIN/picoclaw" ]; then
    if pgrep -f "picoclaw gateway" >/dev/null; then
      echo "pico  : another gateway is already running — left untouched"
    else
      ( cd "\$ROOT/picoclaw"
        PICOCLAW_HOME="\$ROOT/picoclaw" nohup "$BIN/picoclaw" gateway >>"\$LOG/picoclaw.log" 2>&1 & echo \$! >"\$VAR/picoclaw.pid" )
      echo "pico  : starting"
    fi
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS -m 1 "http://127.0.0.1:\$BRIDGE_PORT/health" >/dev/null 2>&1 && break
    sleep 1
  done
  status
}

stop() {
  for f in "\$VAR"/*.pid; do
    [ -f "\$f" ] || continue
    kill "\$(cat "\$f")" 2>/dev/null && echo "stopped \$(basename "\$f" .pid)"
    rm -f "\$f"
  done
}

status() {
  local h g
  h="\$(curl -fsS -m 2 "http://127.0.0.1:\$BRIDGE_PORT/health" 2>/dev/null || echo down)"
  g="\$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:\$GOWA_PORT/app/devices" 2>/dev/null || echo down)"
  printf 'crm   : %s\n' "\$h"
  case "\$g" in
    200|401) printf 'gowa  : up (http %s)\n' "\$g" ;;
    *) printf 'gowa  : %s\n' "\$g" ;;
  esac
  pgrep -f "picoclaw gateway" >/dev/null && echo 'pico  : up' || echo 'pico  : down'
}

case "\${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  logs) tail -n 80 "\$LOG"/*.log 2>/dev/null ;;
  *) echo "usage: crmctl {start|stop|restart|status|logs}"; exit 1 ;;
esac
EOF
  chmod +x "$BIN/crmctl"
}

write_service() {
  [ "$NO_SERVICE" = 1 ] && return
  if is_termux && command -v sv >/dev/null 2>&1; then
    say "runit service -> $PREFIX/var/service/crm"
    [ "$DRY" = 1 ] && return
    mkdir -p "$PREFIX/var/service/crm"
    cat > "$PREFIX/var/service/crm/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
exec 2>&1
exec $BIN/crmctl start
EOF
    chmod +x "$PREFIX/var/service/crm/run"
  elif command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then
    say "systemd unit -> /etc/systemd/system/whatsapp-crm.service"
    [ "$DRY" = 1 ] && return
    cat > /etc/systemd/system/whatsapp-crm.service <<EOF
[Unit]
Description=WhatsApp Channel CRM (GOWA + bridge + PicoClaw)
After=network-online.target

[Service]
Type=forking
User=${SUDO_USER:-root}
ExecStart=$BIN/crmctl start
ExecStop=$BIN/crmctl stop
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now whatsapp-crm.service
  else
    warn "no service manager detected — start with: $BIN/crmctl start"
  fi
}

show_qr() {
  local out="$VAR/whatsapp-qr.png"
  say "Requesting a pairing QR from GOWA (:$GOWA_PORT)"
  if curl -fsS "http://127.0.0.1:$GOWA_PORT/app/login" -o "$out" 2>/dev/null; then
    printf 'QR saved to %s — open it and scan from WhatsApp > Linked devices\n' "$out"
  else
    warn "GOWA not answering yet. Open http://127.0.0.1:$GOWA_PORT and pair from the built-in UI."
  fi
}

summary() {
  cat <<EOF

$(printf '\033[1;32mDone.\033[0m')

  control  : $BIN/crmctl {start|stop|restart|status|logs}
  UI       : http://127.0.0.1:$BRIDGE_PORT/ui   (user: anything · password: BRIDGE_TOKEN)
  secrets  : $ETC/crm.env
  pairing  : bash scripts/install.sh --qr

What is done / what is left:

  [x] GOWA gateway        :3000   (binary in $BIN/gowa)
  [x] CRM + MCP           :$BRIDGE_PORT  (UI + 16 tools)
  [x] PicoClaw agent      :18790  (MCP server 'crm' registered)
  [x] tailscaled unit     :$VAR/tailscaled.sock (userspace networking)

  [ ] WhatsApp pairing    -> bash scripts/install.sh --qr   (scan once per device)
  [ ] Tailscale login     -> open the link printed above, then: bash scripts/install.sh --finish
  [ ] Agent model key     -> PICOCLAW_HOME=$ROOT/picoclaw $BIN/picoclaw onboard
  [ ] Push notifications  -> Telegram bot token, or pkg install termux-api + Termux:API app

Everything else (ports, tokens, MCP wiring, skills) is already configured.
Guides: docs/SETUP-FROM-ZERO.md · docs/PAIRING-GOWA.md · docs/TELEGRAM-AGENT.md
EOF
}

banner() {
  say "WhatsApp Channel CRM installer (mode: $MODE, target: $ROOT)"
  case "$MODE" in
    install)
      install_deps
      run mkdir -p "$BIN" "$ETC" "$VAR" "$LOG"
      [ "$SKIP_GOWA" = 1 ] || install_gowa
      [ "$SKIP_PICO" = 1 ] || install_picoclaw
      install_crm
      write_configs
      setup_pico
      write_crmctl
      write_service
      [ "$DRY" = 1 ] || "$BIN/crmctl" start || true
      if [ "$SKIP_TAILSCALE" = 0 ]; then
        install_tailscale || warn "tailscale download failed; install it manually (docs/SETUP-FROM-ZERO.md)"
        tailscale_unit
        tailscale_login
      fi
      summary
      ;;
    tailscale)
      install_tailscale
      tailscale_unit
      tailscale_login
      tailscale_serve || true
      ;;
    finish)
      tailscale_serve || warn "tailscale is not logged in yet — open the login link first"
      summary
      ;;
    upgrade)
      install_gowa
      install_picoclaw
      install_crm
      [ "$DRY" = 1 ] || "$BIN/crmctl" restart
      say "Upgraded GOWA / PicoClaw / CRM to the latest release"
      ;;
    qr) show_qr ;;
  esac
}

banner
