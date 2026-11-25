#!/data/data/com.termux/files/usr/bin/bash
# Install / refresh the EspoCRM side: custom entity, layouts, PHP hook,
# nginx vhost, and the bridge's API user + key.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TERMUX_HOME="${HOME:-/data/data/com.termux/files/home}"
ESPO_DIR="${ESPO_DIR:-$TERMUX_HOME/espocrm}"
# Reuse an existing EspoCRM instead of installing a second 190 MB copy.
if [ ! -d "$ESPO_DIR" ] && [ -d "$TERMUX_HOME/sanad/espocrm" ]; then
  ESPO_DIR="$TERMUX_HOME/sanad/espocrm"
fi
BASE="$TERMUX_HOME/gowa-espo"
PREFIX="${PREFIX:?run inside Termux}"
step() { printf '\n=== %s ===\n' "$*"; }

[ -d "$ESPO_DIR" ] || { echo "EspoCRM not found at $ESPO_DIR" >&2; exit 1; }

# load secrets (DB password, admin password, bridge token)
set -a; . "$BASE/.env"; set +a
ESPO_DB_PASSWORD="${ESPO_DB_PASSWORD:?missing ESPO_DB_PASSWORD in .env}"
ESPO_ADMIN_PASSWORD="${ESPO_ADMIN_PASSWORD:?missing ESPO_ADMIN_PASSWORD in .env}"

step "database + user"
mariadb -u root -e "CREATE DATABASE IF NOT EXISTS espocrm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mariadb -u root -e "CREATE USER IF NOT EXISTS 'espo'@'127.0.0.1' IDENTIFIED BY '$ESPO_DB_PASSWORD';
                    ALTER USER 'espo'@'127.0.0.1' IDENTIFIED BY '$ESPO_DB_PASSWORD';
                    GRANT ALL PRIVILEGES ON espocrm.* TO 'espo'@'127.0.0.1'; FLUSH PRIVILEGES;"

step "custom entity files"
install -d "$ESPO_DIR/custom/Espo/Custom/Resources/metadata"/{scopes,entityDefs,clientDefs}
install -d "$ESPO_DIR/custom/Espo/Custom/Resources/layouts/WhatsAppChannelPost"
install -d "$ESPO_DIR/custom/Espo/Custom"/{Controllers,Entities,Hooks/WhatsAppChannelPost}
cp "$HERE"/metadata/scopes/*.json      "$ESPO_DIR/custom/Espo/Custom/Resources/metadata/scopes/"
cp "$HERE"/metadata/entityDefs/*.json  "$ESPO_DIR/custom/Espo/Custom/Resources/metadata/entityDefs/"
cp "$HERE"/metadata/clientDefs/*.json  "$ESPO_DIR/custom/Espo/Custom/Resources/metadata/clientDefs/"
cp "$HERE"/layouts/WhatsAppChannelPost/*.json "$ESPO_DIR/custom/Espo/Custom/Resources/layouts/WhatsAppChannelPost/"
cp "$HERE"/Controllers/*.php "$ESPO_DIR/custom/Espo/Custom/Controllers/"
cp "$HERE"/Entities/*.php    "$ESPO_DIR/custom/Espo/Custom/Entities/"
cp "$HERE"/Hooks/WhatsAppChannelPost/*.php "$ESPO_DIR/custom/Espo/Custom/Hooks/WhatsAppChannelPost/"
chmod -R u+rwX "$ESPO_DIR/custom" "$ESPO_DIR/data"

step "nginx vhost"
sed "s|__ESPO_ROOT__|$ESPO_DIR|g" "$HERE/nginx-espocrm.conf" \
  > "$PREFIX/etc/nginx/conf.d/espocrm.conf"
chmod 644 "$PREFIX/etc/nginx/conf.d/espocrm.conf"
nginx -t
export SVDIR="$PREFIX/var/service"
sv restart nginx 2>/dev/null || sv up nginx

cd "$ESPO_DIR"
INSTALLED=$(php -r '$c=@include "data/config-internal.php"; echo (is_array($c) && !empty($c["isInstalled"])) ? "yes" : "no";' 2>/dev/null || echo no)

if [ "$INSTALLED" != "yes" ]; then
  step "headless install"
  php bin/command config:populate
  php bin/command config:set defaultPermissions.user "$(id -un)"
  php bin/command config:set defaultPermissions.group "$(id -gn)"
  php bin/command config:set database.platform Mysql
  php bin/command config:set database.host 127.0.0.1
  php bin/command config:set database.port 3306
  php bin/command config:set database.dbname espocrm
  php bin/command config:set database.user espo
  php bin/command config:set database.password "$ESPO_DB_PASSWORD"
  php bin/command rebuild
  php bin/command create-admin-user admin 2>/dev/null || echo "admin user already exists"
  printf '%s\n' "$ESPO_ADMIN_PASSWORD" | php bin/command set-password admin
  php bin/command config:set language ar_AR
  php bin/command config:set siteUrl http://127.0.0.1:8081
  php bin/command populate-scheduled-jobs
  php bin/command config:set isInstalled true --type=bool
else
  step "already installed — refreshing metadata"
  php bin/command clear-cache
  php bin/command rebuild
fi

step "bridge API user + key"
KEY=$(python3 "$HERE/../scripts/espocrm-bootstrap.py" \
  --base-url http://127.0.0.1:8081 \
  --admin-user admin \
  --admin-pass "$ESPO_ADMIN_PASSWORD")
if [ -n "$KEY" ]; then
  python3 - "$BASE/.env" "$KEY" <<'PY'
import re, sys, os
path, key = sys.argv[1], sys.argv[2]
text = open(path).read()
text = re.sub(r"^ESPO_API_KEY=.*$", "ESPO_API_KEY=" + key, text, flags=re.M)
open(path, "w").write(text)
os.chmod(path, 0o600)
print("ESPO_API_KEY written to", path)
PY
fi

step "verify"
curl -s -o /dev/null -w 'web http=%{http_code}\n' --max-time 10 http://127.0.0.1:8081/
curl -s --max-time 10 -H "X-Api-Key: $(grep '^ESPO_API_KEY=' "$BASE/.env" | cut -d= -f2-)" \
  http://127.0.0.1:8081/api/v1/WhatsAppChannelPost?maxSize=1 >/dev/null \
  && echo "api ok" || echo "api check failed"
