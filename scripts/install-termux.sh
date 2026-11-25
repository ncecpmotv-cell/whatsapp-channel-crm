#!/data/data/com.termux/files/usr/bin/bash
# ---------------------------------------------------------------------------
# GOWA + EspoCRM + bridge installer for Termux (no root, no Docker).
# Idempotent: safe to re-run; every step checks before acting.
#
# Usage:
#   bash install-termux.sh                 # full install
#   bash install-termux.sh --skip-espocrm  # only GOWA + bridge
#
# Expected to run INSIDE Termux on the phone. The GOWA binary must already be
# produced by scripts/build-gowa-arm64.sh and copied to ~/gowa-espo/bin/whatsapp.
# ---------------------------------------------------------------------------
set -euo pipefail
TERMUX_HOME="${HOME:-/data/data/com.termux/files/home}"
BASE="$TERMUX_HOME/gowa-espo"
ESPO_DIR="${ESPO_DIR:-$TERMUX_HOME/espocrm}"
if [ ! -d "$ESPO_DIR" ] && [ -d "$TERMUX_HOME/sanad/espocrm" ]; then
  ESPO_DIR="$TERMUX_HOME/sanad/espocrm"
fi
export ESPO_DIR
DB_NAME="espocrm"
DB_USER="espo"
SKIP_ESPO=0
[ "${1:-}" = "--skip-espocrm" ] && SKIP_ESPO=1

step() { printf '\n=== %s ===\n' "$*"; }

step "preflight"
[ -n "${PREFIX:-}" ] || { echo "This script must run inside Termux (PREFIX is unset)." >&2; exit 1; }
ARCH="$(uname -m)"
[ "$ARCH" = "aarch64" ] || echo "WARNING: expected aarch64, found $ARCH"
free -m | sed -n '2p'
df -h "$HOME" | tail -1

step "packages"
pkg update -y >/dev/null 2>&1 || true
pkg install -y git curl unzip php php-fpm php-gd mariadb nginx python termux-services proot ca-certificates cronie 2>&1 | tail -3
php -m | grep -qx pdo_mysql || { echo "php lacks pdo_mysql" >&2; exit 1; }

step "directories"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$BASE"/{bin,etc,var,logs} "$BASE/bridge/tests" "$PREFIX/var/log/sv"
mkdir -p "$PREFIX/var/service"

step "bridge source"
cp -f "$REPO_ROOT"/bridge/*.py "$BASE/bridge/"
cp -f "$REPO_ROOT"/bridge/tests/*.py "$BASE/bridge/tests/"
echo "copied bridge source -> $BASE/bridge"

step "runtime config (.env)"
if [ ! -f "$BASE/.env" ]; then
  SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
  TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
  DBPASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
  ADMINPASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
  sed -e "s|^GOWA_WEBHOOK_SECRET=.*|GOWA_WEBHOOK_SECRET=$SECRET|" \
      -e "s|^BRIDGE_TOKEN=.*|BRIDGE_TOKEN=$TOKEN|" \
      -e "s|^BRIDGE_DB_PATH=.*|BRIDGE_DB_PATH=$BASE/var/bridge.db|" \
      -e "s|^ESPO_DB_PASSWORD=.*|ESPO_DB_PASSWORD=$DBPASS|" \
      -e "s|^ESPO_ADMIN_PASSWORD=.*|ESPO_ADMIN_PASSWORD=$ADMINPASS|" \
      "$(dirname "$0")/../.env.example" > "$BASE/.env"
  chmod 600 "$BASE/.env"
  echo "generated $BASE/.env with fresh secrets"
else
  echo "keeping existing $BASE/.env"
fi

step "Android DNS + CA bundle for Go"
printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\nnameserver 9.9.9.9\n' > "$BASE/etc/resolv.conf"

if [ "$SKIP_ESPO" = "0" ]; then
  step "MariaDB"
  if [ ! -d "$PREFIX/var/lib/mysql/mysql" ]; then
    mariadb-install-db --datadir="$PREFIX/var/lib/mysql" --auth-root-authentication-method=normal 2>&1 | tail -2
  fi
  cp "$(dirname "$0")/maria-low-ram.cnf" "$PREFIX/etc/my.cnf.d/zz-low-ram.cnf" 2>/dev/null || true
  install -Dm755 "$(dirname "$0")/runit/mariadb/run" "$PREFIX/var/service/mariadb/run"
  install -Dm755 "$(dirname "$0")/runit/mariadb/log/run" "$PREFIX/var/service/mariadb/log/run"
  export SVDIR="$PREFIX/var/service"
  service-daemon start 2>/dev/null || true
  sv up mariadb || true
  for i in $(seq 1 30); do mariadb -u root -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done
  mariadb -u root -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  mariadb -u root -e "CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$(sed -n 's/^ESPO_DB_PASSWORD=//p' "$BASE/.env" || true)';" 2>/dev/null || true
  echo "MariaDB ready"

  step "PHP-FPM"
  [ -f "$PREFIX/etc/php/php.ini" ] || cp "$PREFIX/etc/php/php.ini-production" "$PREFIX/etc/php/php.ini"
  php -r '$p=getenv("PREFIX")."/etc/php/php.ini"; $s=file_get_contents($p);
    $s=preg_replace("/^memory_limit.*$/m","memory_limit = 192M",$s);
    $s=preg_replace("/^;?date.timezone.*$/m","date.timezone = Asia/Riyadh",$s);
    file_put_contents($p,$s);'
  install -Dm755 "$(dirname "$0")/runit/php-fpm/run" "$PREFIX/var/service/php-fpm/run"
  install -Dm755 "$(dirname "$0")/runit/php-fpm/log/run" "$PREFIX/var/service/php-fpm/log/run"
  sv up php-fpm || true
  echo "PHP-FPM ready"

  step "nginx"
  grep -q 'conf.d/\*.conf' "$PREFIX/etc/nginx/nginx.conf" || \
    sed -i 's|^http {|http {\n    include '"$PREFIX"'/etc/nginx/conf.d/*.conf;|' "$PREFIX/etc/nginx/nginx.conf"
  install -Dm755 "$(dirname "$0")/runit/nginx/run" "$PREFIX/var/service/nginx/run"
  install -Dm755 "$(dirname "$0")/runit/nginx/log/run" "$PREFIX/var/service/nginx/log/run"
  sv up nginx || true
  echo "nginx ready (vhost is installed by setup-espocrm.sh)"

  step "EspoCRM source"
  if [ -f "$ESPO_DIR/index.php" ]; then
    echo "reusing existing EspoCRM at $ESPO_DIR (no second copy)"
  else
    VER=$(curl -sL https://api.github.com/repos/espocrm/espocrm/releases/latest | sed -n 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/p' | head -1)
    VER="${VER:-10.1.4}"
    echo "downloading EspoCRM $VER"
    curl -fL --retry 3 -o "$BASE/espocrm.zip" \
      "https://github.com/espocrm/espocrm/releases/download/v${VER}/EspoCRM-${VER}.zip"
    unzip -q -o "$BASE/espocrm.zip" -d "$TERMUX_HOME"
    rm -f "$BASE/espocrm.zip"
  fi
  [ -d "$ESPO_DIR" ] || { echo "EspoCRM directory not found" >&2; exit 1; }
  chmod -R u+rwX "$ESPO_DIR/data" "$ESPO_DIR/custom" 2>/dev/null || true
  bash "$(dirname "$0")/../espocrm-custom/setup-espocrm.sh"
fi

step "GOWA binary"
if [ ! -x "$BASE/bin/whatsapp" ]; then
  echo "MISSING: $BASE/bin/whatsapp"
  echo "Build it on another machine:  ./build-gowa-arm64.sh && scp whatsapp <phone>:$BASE/bin/whatsapp"
  echo "The official glibc release will NOT run on Termux."
else
  "$BASE/bin/whatsapp" version 2>&1 | head -2 || true
fi

step "services: gowa + bridge"
for svc in gowa bridge; do
  install -Dm755 "$(dirname "$0")/runit/$svc/run" "$PREFIX/var/service/$svc/run"
  install -Dm755 "$(dirname "$0")/runit/$svc/log/run" "$PREFIX/var/service/$svc/log/run"
  sv up "$svc" || true
done

step "espocrm cron (scheduled jobs)"
CRON_LINE="* * * * * php $ESPO_DIR/cron.php >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -vF "$ESPO_DIR/cron.php"; echo "$CRON_LINE" ) | crontab -
install -Dm755 "$(dirname "$0")/runit/crond/run" "$PREFIX/var/service/crond/run"
install -Dm755 "$(dirname "$0")/runit/crond/log/run" "$PREFIX/var/service/crond/log/run"
sv up crond || true

step "done"
echo "wakelock: run 'termux-wake-lock' (or use scripts/termux-boot/00-server.sh)"
echo "health : bash $(dirname "$0")/start-all.sh"
