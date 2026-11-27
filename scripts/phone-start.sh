#!/data/data/com.termux/files/usr/bin/sh
# The phone is the runtime. One command after a reboot:
#
#   sh ~/start.sh            start everything + status
#   sh ~/start.sh status     status only
#   sh ~/start.sh stop       stop the stack (keeps ssh/tunnel up)
#   sh ~/start.sh legacy     start the retired EspoCRM stack (should stay off)
#
# Stack (runit services, in dependency order):
#   gowa      WhatsApp gateway, 127.0.0.1:3000
#   crm       the CRM + MCP server, 127.0.0.1:8085
#   picoclaw  the agent gateway, 127.0.0.1:18790
# Infrastructure: sshd, rtunnel (maintenance access), tailscaled, crond.
set -u

SVDIR="${SVDIR:-$PREFIX/var/service}"
export SVDIR
INFRA="sshd rtunnel tailscaled crond"
STACK="gowa crm picoclaw"
LEGACY="mariadb php-fpm nginx bridge"

say() { printf '==> %s\n' "$*"; }

line() {
  for s in "$@"; do
    if sv status "$SVDIR/$s" 2>/dev/null | grep -q '^run:'; then
      printf '  %-10s up\n' "$s"
    else
      printf '  %-10s down\n' "$s"
    fi
  done
}

wait_http() {  # url, seconds
  i=0
  while [ "$i" -lt "$2" ]; do
    curl -fsS -m 2 "$1" >/dev/null 2>&1 && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

start_all() {
  termux-wake-lock 2>/dev/null || true
  export SVDIR
  command -v service-daemon >/dev/null 2>&1 && { service-daemon start 2>/dev/null || true; sleep 3; }

  say "infrastructure"
  for s in $INFRA; do sv up "$s" 2>/dev/null; done
  sleep 1
  sv up rtunnel 2>/dev/null   # re-bind after sshd is really listening

  say "stack"
  sv up gowa 2>/dev/null
  wait_http http://127.0.0.1:3000/health 25 || say "gowa is slow — check: tail -f $SVDIR/gowa/log/current"
  sv up crm 2>/dev/null
  wait_http http://127.0.0.1:8085/health 20 || say "crm did not answer /health"
  sv up picoclaw 2>/dev/null
  sleep 2
}

case "${1:-start}" in
  status)
    line $INFRA $STACK $LEGACY
    ;;
  start)
    start_all
    line $INFRA
    line $STACK
    say "retired stack (stays off)"
    line $LEGACY
    free -m 2>/dev/null | head -2
    ;;
  stop)
    say "stopping the stack (ssh and the tunnel stay up)"
    for s in picoclaw crm gowa; do sv down "$s" 2>/dev/null; done
    line $STACK
    ;;
  restart)
    for s in picoclaw crm gowa; do sv down "$s" 2>/dev/null; done
    sleep 2
    start_all
    line $STACK
    ;;
  legacy)
    say "starting the retired EspoCRM stack"
    for s in mariadb php-fpm nginx bridge; do sv up "$s" 2>/dev/null; done
    line $LEGACY
    ;;
  *)
    echo "usage: sh $0 [start|status|stop|restart|legacy]"; exit 2 ;;
esac
