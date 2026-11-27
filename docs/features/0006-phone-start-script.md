# 0006 — Phone start script: ordered, honest, runit-native

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.1.1 (pidfile variant) · v3.0.0 (runit variant)
- **Roadmap:** R-15
- **Files:** `scripts/phone-start.sh`, `docs/ANDROID-BACKGROUND.md`

## Why

After an Android reboot the owner ran `sh start.sh` and had no way to know whether the stack
came back: the old script started processes without checking ports and printed nothing that
distinguished "running" from "started and died". A reboot is the most common failure moment on
a phone, so the script has to be the most predictable part of the system.

The first version managed bare processes with pidfiles. Once the stack moved onto the phone
(see [0007](0007-stack-on-the-phone.md)) the services are runit units, so the script became a
thin, ordered front-end over `sv` — the supervisor, not the script, owns restart loops.

## How

`scripts/phone-start.sh`, deployed as `~/start.sh`, with
`start | status | stop | restart | legacy`:

- **Order is a dependency list, not a hope:** infrastructure (`sshd`, `rtunnel`,
  `tailscaled`, `crond`) → `gowa` → wait for `:3000/health` → `crm` → wait for
  `:8085/health` → `picoclaw`. The reverse tunnel is re-`up`ed after sshd is listening,
  because it binds a port on the far side.
- **Idempotent:** `sv up` on a running unit is a no-op; running the script twice is safe.
- **Honest status:** one line per unit, `up`/`down`, plus free memory. `status` is the answer
  to "is it actually running?" — not `ps`.
- **Retired stack is visible but never started:** `mariadb`, `php-fpm`, `nginx`, `bridge`
  are printed as down; `legacy` is the only way to start them.
- **Wake lock** is taken on start, so Android is less likely to freeze the stack.
- **One entry point:** `~/.termux/boot/00-server.sh` calls `~/start.sh`; there is no second
  list of services to drift.

## Verify

```bash
sh ~/start.sh status
# sshd up · rtunnel up · tailscaled up · crond up
# gowa up · crm up · picoclaw up
# mariadb down · php-fpm down · nginx down · bridge down

sh ~/start.sh restart      # down the three stack units, start them in order, re-print
curl -s 127.0.0.1:8085/health   # {"ok": true, "crm": true}
curl -s 127.0.0.1:18790/health  # {"status":"ok", ...}
```

Run on the device after the migration: both health endpoints answered within the script's
waits, and a second `start` changed nothing.

## Limits

- It does not pair WhatsApp: a missing session still needs a QR scan.
- If a unit crash-loops, `status` shows `down`; the reason is in
  `$PREFIX/var/log/sv/<unit>/current`, not in the script's output.
- The wake lock is best-effort; Android can still freeze a backgrounded Termux.

## Links

- `docs/ANDROID-BACKGROUND.md`
- `docs/DEPLOY.md`
- [0007 — the stack on the phone](0007-stack-on-the-phone.md)
