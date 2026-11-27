#!/usr/bin/env bash
# Phone-side launcher for a Termux install of the stack (GOWA + CRM + optional PicoClaw).
#
#   sh scripts/termux-start.sh start      # default: start what is down, verify, print status
#   sh scripts/termux-start.sh status
#   sh scripts/termux-start.sh restart
#   sh scripts/termux-start.sh stop
#   sh scripts/termux-start.sh logs
#
# Why this replaces a naive `start.sh`:
#   * it is idempotent — running it twice does not spawn a second GOWA/bridge;
#   * it starts in dependency order and waits for each health signal, so "started" means
#     "answering", not "the process exists";
#   * it refuses to start a local GOWA when the config points at a remote one, which is how
#     you get two WhatsApp sessions fighting over one account;
#   * it logs to files, keeps pidfiles, and reports one line per service;
#   * it can hold a Termux wake lock, because Android otherwise freezes the stack.
# `sh start.sh` must work: re-exec under bash before any bash-only option is set.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -uo pipefail

ROOT="${CRM_HOME:-$HOME/gowa-espo}"
ENVF="${ENV_FILE:-$ROOT/.env}"
LOG="$ROOT/var/log"
RUN="$ROOT/var/run"
GOWA_PORT="${GOWA_PORT:-3000}"
BRIDGE_PORT="${BRIDGE_PORT:-8085}"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

need_env() {
  [ -f "$ENVF" ] || die "no $ENVF — run the installer first (scripts/install.sh) or copy .env.example"
  set -a; . "$ENVF"; set +a
}

port_open() {  # host:port -> 0 when something accepts a TCP connection
  local host="$1" port="$2"
  (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null && { exec 3<&-; return 0; } || return 1
}

running() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

start_one() {  # name, workdir, command...
  local name="$1" dir="$2"; shift 2
  mkdir -p "$RUN" "$LOG"
  ( cd "$dir" || exit 1
    nohup "$@" >>"$LOG/$name.log" 2>&1 &
    echo $! >"$RUN/$name.pid" )
  running "$name" || { warn "$name exited immediately — see $LOG/$name.log"; return 1; }
  return 0
}

stop_one() {
  local name="$1"
  if running "$name"; then
    kill "$(cat "$RUN/$name.pid")" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do running "$name" || break; sleep 0.3; done
    running "$name" && { warn "$name ignored SIGTERM — sending KILL"; kill -9 "$(cat "$RUN/$name.pid")" 2>/dev/null; }
    echo "stopped $name"
  fi
  rm -f "$RUN/$name.pid"
}

remote_gowa() {  # true when the config points GOWA at something other than loopback
  case "${GOWA_BASE_URL:-http://127.0.0.1:$GOWA_PORT}" in
    *127.0.0.1*|*localhost*) return 1 ;;
    *) return 0 ;;
  esac
}

start() {
  need_env
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null || true

  if remote_gowa; then
    warn "GOWA_BASE_URL=$GOWA_BASE_URL — the gateway runs elsewhere, not starting a local one."
    warn "Starting a second GOWA on the same WhatsApp account logs the other session out."
  elif port_open 127.0.0.1 "$GOWA_PORT"; then
    say "GOWA already listening on $GOWA_PORT"
  else
    say "starting GOWA on $GOWA_PORT"
    start_one gowa "$ROOT" "$ROOT/bin/gowa" rest || true
    for _ in $(seq 20); do port_open 127.0.0.1 "$GOWA_PORT" && break; sleep 0.5; done
    port_open 127.0.0.1 "$GOWA_PORT" || warn "GOWA did not open $GOWA_PORT (pairing may be needed)"
  fi

  if curl -fsS -m 2 "http://127.0.0.1:$BRIDGE_PORT/health" >/dev/null 2>&1; then
    say "CRM already answering on $BRIDGE_PORT"
  else
    say "starting CRM bridge on $BRIDGE_PORT"
    start_one crm "$ROOT" python3 "$ROOT/bridge/app.py" || true
    for _ in $(seq 20); do
      curl -fsS -m 1 "http://127.0.0.1:$BRIDGE_PORT/health" >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi

  if [ -x "$ROOT/bin/picoclaw" ] && [ -f "$ROOT/picoclaw/config.json" ]; then
    if running picoclaw || pgrep -f "$ROOT/bin/picoclaw" >/dev/null; then
      say "PicoClaw gateway already running"
    else
      say "starting PicoClaw gateway"
      start_one picoclaw "$ROOT/picoclaw" env PICOCLAW_HOME="$ROOT/picoclaw" "$ROOT/bin/picoclaw" gateway || true
    fi
  fi

  status
}

stop() {
  stop_one picoclaw
  stop_one crm
  stop_one gowa
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null || true
}

status() {
  local g c p
  if port_open 127.0.0.1 "$GOWA_PORT"; then g="up :$GOWA_PORT"; else g="down"; fi
  c="$(curl -fsS -m 2 "http://127.0.0.1:$BRIDGE_PORT/health" 2>/dev/null || echo down)"
  if running picoclaw || pgrep -f "$ROOT/bin/picoclaw" >/dev/null; then p="up"; else p="down"; fi
  printf 'gowa  : %s\ncrm   : %s\npico  : %s\n' "$g" "$c" "$p"
  local fails=0
  [ "$g" = "down" ] && fails=1
  case "$c" in down*) fails=1 ;; esac
  return "$fails"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) need_env 2>/dev/null || true; status ;;
  logs) tail -n 80 "$LOG"/*.log 2>/dev/null || echo "no logs in $LOG" ;;
  *) echo "usage: $0 {start|stop|restart|status|logs}"; exit 2 ;;
esac
