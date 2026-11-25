#!/data/data/com.termux/files/usr/bin/sh
# Runs at boot via the Termux:Boot app (F-Droid). Brings the whole stack up in
# dependency order, so the device stays reachable even if the web stack fails.
termux-wake-lock
export SVDIR=$PREFIX/var/service
$PREFIX/bin/service-daemon start
sleep 5

# reachability first
for s in sshd rtunnel webforward crond; do sv up "$s" 2>/dev/null; done

# database, then wait until it actually accepts connections
sv up mariadb 2>/dev/null
i=0
while [ $i -lt 60 ]; do
  mariadb -u root -e 'SELECT 1' >/dev/null 2>&1 && break
  sleep 1; i=$((i+1))
done

for s in php-fpm nginx gowa bridge; do sv up "$s" 2>/dev/null; done
sleep 3
sv up webforward 2>/dev/null
