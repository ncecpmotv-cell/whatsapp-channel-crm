# 0006 — Phone start script: idempotent, ordered, honest

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.1.1
- **Roadmap:** R-15
- **Files:** `scripts/termux-start.sh`, `scripts/termux-infra-start.sh`, `docs/ANDROID-BACKGROUND.md`

## Why

After an Android reboot the owner ran `sh start.sh` and had no way to know whether the stack
came back: the old script started processes without checking ports, could spawn a second
GOWA (which logs the other session out), and printed nothing that distinguished "running"
from "started and died". A reboot is the most common failure moment on a phone, so the
script has to be the most predictable part of the system.

## How

`scripts/termux-start.sh` with five subcommands (`start|stop|restart|status|logs`):

- **Re-exec under bash** when invoked with `sh`, before any bash-only option is parsed.
- **Idempotent:** checks the port/health first; a second run does nothing instead of starting
  a twin process. Pidfiles live in `var/run`.
- **Dependency order with waits:** GOWA → wait for the port → CRM → wait for `/health` →
  PicoClaw (only if binary + config exist and no gateway is already running).
- **Remote guard:** if `GOWA_BASE_URL` is not loopback it refuses to start a local GOWA and
  says why — two sessions on one WhatsApp account is a support incident, not a start-up.
- **Honest status:** one line per service plus a non-zero exit code when any is down, so it
  can be used in `cron`, Termux:Boot, or a health check.
- **Wake lock:** takes it when `termux-wake-lock` exists, releases it on `stop`.

## The second variant: infrastructure-only phone

On the owner's phone the CRM runs on the server, so `scripts/termux-infra-start.sh`
(deployed as `~/start.sh`) starts only what the phone is for: `sshd`, the reverse tunnel
the maintenance access uses (`127.0.0.1:2225`), its tailscale node and `crond`. It then
prints one line per unit, and keeps `gowa / bridge / mariadb / php-fpm / nginx` **down** by
default with a `--legacy` escape hatch.

Two more pieces make that state survive a reboot:

- `~/.termux/boot/00-server.sh` no longer names individual services — it calls
  `~/start.sh`, so there is one list, not two that drift;
- `sv-disable` leaves a `down` marker for each legacy unit, so `runsvdir` does not start
  them on boot.

Measured on the phone: the legacy stack held ~700 MB and one unpaired GOWA; after disabling
it, `available` went from 618 MB to ~710 MB with ssh/tunnel/tailscale still up.

## Verify

```bash
bash -n scripts/termux-start.sh
CRM_HOME=/tmp/phonesim sh scripts/termux-start.sh status   # re-exec works under sh
# gowa : down / crm : down / pico : down   → exit 1

CRM_HOME=/tmp/nonexistent sh scripts/termux-start.sh start
# [x] no /tmp/nonexistent/.env — run the installer first

# remote guard
GOWA_BASE_URL=https://crm.example.test … start
# [!] the gateway runs elsewhere, not starting a local one.
```

## Limits

- Not executed on a real Termux device in this change; POSIX/bash behaviour was verified on
  Linux. The Termux-specific parts (wake lock) degrade silently when the command is absent.
- It does not pair WhatsApp: a missing session still needs a QR scan.
- `status` reports PicoClaw by pidfile or path; a gateway started by another user/homedir is
  reported as down by design.

## Links

- `docs/ANDROID-BACKGROUND.md`
- `docs/DEPLOY.md`
- CHANGELOG: "Phone start script…"
