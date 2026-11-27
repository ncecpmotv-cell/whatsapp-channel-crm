#!/data/data/com.termux/files/usr/bin/sh
# One command after a phone reboot.
#
# This phone is INFRASTRUCTURE only: ssh (8022) + the reverse tunnel the server
# reaches at 127.0.0.1:2225 + its tailscale node + cron.
#
# The CRM and the WhatsApp gateway run on the server (crm-node / crm-app /
# crm-gowa). Starting the old local stack here costs ~700 MB, leaves an unpaired
# GOWA running, and once put two WhatsApp sessions on one number. It is off by
# default; `--legacy` exists only for the deliberate day the CRM moves back.
#
#   sh ~/start.sh            start infrastructure + status
#   sh ~/start.sh status     status only
#   sh ~/start.sh --legacy   also start gowa + bridge + the old web stack
#   sh ~/start.sh stop       stop the legacy stack
set -u

SVDIR="${SVDIR:-$PREFIX/var/service}"
INFRA="sshd rtunnel tailscaled crond"
LEGACY="gowa bridge mariadb php-fpm nginx"

say() { printf '==> %s\n' "$*"; }

status_line() {
  for s in "$@"; do
    if sv status "$SVDIR/$s" 2>/dev/null | grep -q '^run:'; then
      printf '  %-11s up\n' "$s"
    else
      printf '  %-11s down\n' "$s"
    fi
  done
}

start_infra() {
  termux-wake-lock 2>/dev/null || true
  export SVDIR
  command -v service-daemon >/dev/null 2>&1 && { service-daemon start 2>/dev/null || true; sleep 3; }
  say "bringing up: $INFRA"
  for s in $INFRA; do sv up "$s" 2>/dev/null; done
  i=0
  while [ "$i" -lt 20 ]; do
    pgrep -f sshd >/dev/null 2>&1 && break
    sleep 1; i=$((i + 1))
  done
  # the tunnel binds a remote port on the server; retry once sshd is really up
  sv up rtunnel 2>/dev/null
  sleep 1
  sv up rtunnel 2>/dev/null
}

case "${1:-start}" in
  status)
    status_line $INFRA $LEGACY
    ;;
  start)
    start_infra
    say "infrastructure"
    status_line $INFRA
    say "legacy stack (off by default)"
    status_line $LEGACY
    free -m 2>/dev/null | head -2
    ;;
  --legacy|legacy)
    start_infra
    say "starting the legacy stack"
    for s in mariadb php-fpm nginx gowa bridge; do sv up "$s" 2>/dev/null; done
    status_line $LEGACY
    ;;
  stop)
    say "stopping the legacy stack"
    for s in gowa bridge nginx php-fpm mariadb; do sv down "$s" 2>/dev/null; done
    status_line $LEGACY
    ;;
  *)
    echo "usage: sh $0 [start|status|--legacy|stop]"; exit 2 ;;
esac
