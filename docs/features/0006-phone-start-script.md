# 0006 — Phone start script: idempotent, ordered, honest

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.1.1
- **Roadmap:** R-15
- **Files:** `scripts/termux-start.sh`, `docs/ANDROID-BACKGROUND.md`

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
