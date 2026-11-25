# Troubleshooting — every failure actually hit during the build

Each entry is a real error string from the reference device (Huawei P Smart
2019, Android 9 / EMUI 9.1, Termux, no root).

## GOWA

### `bash: ./whatsapp: cannot execute: required file not found`

The binary is glibc-linked. Check with:

```bash
readelf -l whatsapp | grep INTERP      # shows /lib/ld-linux-aarch64.so.1
readelf -d whatsapp | grep NEEDED      # shows libc.so.6
```

Termux has no glibc loader. Build the static musl binary instead:
`scripts/build-gowa-arm64.sh`.

### `failed to initialize chat storage: ... go-sqlite3 requires cgo to work`

You built with `CGO_ENABLED=0`. GOWA's SQLite driver requires cgo. Build with
`CGO_ENABLED=1` and a musl/static toolchain (the script does this).

### `lookup web.whatsapp.com on [::1]:53: read udp ... connection refused`

Go's resolver reads `/etc/resolv.conf`, which does not exist on Android. Run
GOWA under proot with a bind-mounted file:

```bash
proot -b ~/gowa-espo/etc/resolv.conf:/etc/resolv.conf ./whatsapp rest …
```

### `tls: failed to verify certificate: x509: certificate signed by unknown authority`

`/etc/ssl/certs` does not exist on Android. Either export
`SSL_CERT_FILE=$PREFIX/etc/tls/cert.pem` or bind-mount it (the runit service
does both).

### `{"code":"DEVICE_ID_REQUIRED"}`

GOWA runs in multi-device mode; every call needs `X-Device-Id`. Create a slot
first:

```bash
curl -X POST localhost:3000/devices -H 'Content-Type: application/json' \
  -d '{"device_id":"primary","webhook_url":"http://127.0.0.1:8085/webhook/gowa"}'
```

### QR expires before it can be scanned

`/devices/primary/login` returns `qr_duration: 30`. Fetch the link, download the
PNG immediately, and re-request if it lapsed.

### `AUTHENTICATION_ERROR ... not connect to services server`

The device slot exists but no WhatsApp session is linked (or it was logged out
from the phone). Re-scan the QR.

## EspoCRM

### The page says "You need to configure your webserver"

EspoCRM 10 moved the front controller to `public/`. A vhost whose `root` is the
project root serves the placeholder `index.php`. Use
`espocrm-custom/nginx-espocrm.conf` (root = project, `index public/index.php`,
`try_files … /public/index.php`, plus a `/api/` rewrite to
`public/api/v1/index.php`).

### `X-Status-Reason: Controller 'X' does not exist`

Custom entities need a controller class, not just metadata:

```
custom/Espo/Custom/Controllers/WhatsAppChannelPost.php
namespace Espo\Custom\Controllers;
class WhatsAppChannelPost extends \Espo\Core\Controllers\Record {}
```

### Entity is 404 even though metadata files exist

- The scope key in Espo 10 is `isCustom`, not `custom`.
- Entity class goes in `custom/Espo/Custom/Entities/<Name>.php`.
- Run `php bin/command clear-cache && php bin/command rebuild`.

### Role update returns `400` with an empty body

`role.data` rejects booleans. Use strings:

```json
{"Contact":{"create":"yes","read":"all","edit":"all","delete":"yes","stream":"yes"}}
```

### `POST /Contact/{id}/stream` returns `200 false` and writes nothing

In Espo 10 that endpoint is a silent no-op. Post notes through the entity:

```json
POST /api/v1/Note
{"type":"Post","parentType":"Contact","parentId":"<id>","post":"..."}
```

### Note creation returns `403 No create access`

Note permission is derived from the **parent** scope's stream permission. The
role needs `"stream":"yes"` on `Contact` / `Lead` / `Case`, not just on `Note`.

### `X-Api-Key` returns `401`

The API user must have `authMethod = "ApiKey"` and `type = "api"`. A key
generated for a regular user authenticates but 403s elsewhere.

### Generating an API key returns `false`

Use the dedicated endpoint:

```bash
curl -u admin:pass -X POST http://127.0.0.1:8081/api/v1/UserSecurity/apiKey/generate \
  -H 'Content-Type: application/json' -d '{"id":"<userId>"}'
```

### Contact creation fails with `field: lastName, type: required`

EspoCRM requires a non-empty `lastName`. Single-word display names must be sent
as `lastName` with an empty `firstName` (the bridge does this).

## Access / tunnel

### `Connection timed out during banner exchange` on the reverse-tunnel port

A stale `sshd` child on the *server* still owns the forwarded port: it accepts
TCP but the far end is gone. Free it (`ss -ltnp | grep 2225`, kill that pid) or
move the tunnel to a new port — which also needs a matching
`permitlisten="127.0.0.1:2225"` entry in the server's `authorized_keys`.

### `nohup ssh -N -R … &` shows `Stopped` and an empty log

ssh asked for the host key on the tty and job control suspended it. Use
`-f -N -T` with `-o BatchMode=yes -o StrictHostKeyChecking=accept-new`.

### Tunnel must not depend on Tailscale

A shared tailnet node can disappear from `tailscale status` and lock you out.
Point the tunnel at the server's public IP (see `scripts/runit/rtunnel/run`).

## Termux / runit

### `sv down gowa` leaves the process running

`proot` ignores `SIGTERM`. Kill by PID, then `sv up`:

```bash
for p in $(ps -eo pid,args | grep 'gowa-espo/bin/whatsapp' | grep -v grep | awk '{print $1}'); do kill -9 "$p"; done
```

### `curl: (23) Failed writing body` / empty files under `/tmp`

`/tmp` is not reliable in Termux. Write to `$HOME` instead.

### php-fpm cannot write `data/` or `custom/`

Set the pool user to the Termux uid (`u0_aNNN`), not `www-data`/`nobody`:

```bash
php bin/command config:set defaultPermissions.user "$(id -un)"
php bin/command config:set defaultPermissions.group "$(id -gn)"
```

### MariaDB crash-loops with `Unable to lock ./ibdata1 error: 11`

Two service units own the same datadir. Termux snapshots often leave both a
legacy `mysqld` unit and a `mariadb` unit; the older process holds the InnoDB
lock and the newer one restarts every second. Keep exactly one:

```bash
touch $PREFIX/var/service/mysqld/down     # never autostart it again
sv down mysqld
kill -9 <legacy mysqld pid>
sv up mariadb
mariadb -u root -e "show global status like 'Uptime';"   # must be small
```

### Port 8080 already answers

That is nginx's stock default vhost (`listen 8080` in `nginx.conf`). EspoCRM is
served on 8081 by this project.

## WhatsApp channels

### Publishing fails with `not-authorized` / no permission

WhatsApp only allows posting to a channel where the linked account is an
**admin/owner**. A follower account can read and monitor, never post.
