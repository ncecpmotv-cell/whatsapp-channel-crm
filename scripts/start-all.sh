#!/data/data/com.termux/files/usr/bin/sh
# One command after a reboot (no Termux:Boot required):
#   sh ~/start.sh
# Brings up the whole stack in dependency order and prints health.
set -u
termux-wake-lock
sh "$HOME/.termux/boot/00-server.sh"
sleep 3
export SVDIR="${SVDIR:-$PREFIX/var/service}"
sv status mariadb php-fpm nginx gowa bridge tailscaled 2>/dev/null \
  | sed 's|/data/data/com.termux/files/usr/var/service/||'
echo "--- health ---"
curl -s --max-time 10 http://127.0.0.1:8085/health
echo
