# Keeping the stack alive on Android (Termux)

Android will happily freeze or kill a background Termux process. The stack is designed to recover — the outbox survives restarts and missed sends resume — but if you want it to stay up, do all four:

## 1. Disable battery optimisation for Termux

- **Settings → Apps → Termux → Battery → Unrestricted** (Samsung: *Sleeping apps → Remove from sleeping apps*).
- **Huawei/EMUI**: *Settings → Battery → App launch → Termux → Manage manually*, and enable **Auto-launch**, **Secondary launch**, **Run in background**.
- **Xiaomi/MIUI**: *Settings → Apps → Termux → Battery saver → No restrictions*; lock the app in the recents screen.

## 2. Hold a wake lock

```bash
pkg install termux-api
termux-wake-lock          # releases on reboot — re-run it, or add to your shell rc
```

Termux's notification then reads “wake lock held”, which is also a useful indicator that the process was not reaped.

## 3. Start it automatically

```bash
pkg install termux-services
sv-enable crm             # the installer wrote $PREFIX/var/service/crm/run
```

If you do not use runit, `~/.whatsapp-crm/bin/crmctl start` from `~/.bashrc` is the fallback (it no-ops when everything is already running).

## 4. Keep the session reachable

- Pair WhatsApp once and do not log out the linked device.
- When the phone reboots, WhatsApp stays paired but Termux is cold: the service starts GOWA, which reconnects with the stored session (no QR needed).
- The bridge is stateless: it re-reads the channel archive on boot, so a long sleep costs nothing but latency.

## What “asleep” looks like

| Symptom | Cause | Fix |
|---|---|---|
| No publishes at the scheduled minute | Termux frozen | Battery settings + wake lock |
| `crmctl status` says `down` after a while | process reaped | `sv-enable crm` or `crmctl start` |
| Sends resume hours late in a burst | the outbox draining on wake | expected; the retry window is 6 h |
| GOWA asks for a QR again | the session was logged out (WhatsApp side) | re-pair once |

## Battery cost

Measured on a mid-range Android device with the stack idle: **0.3–0.8 %/hour** with the screen off, roughly 2 %/hour while publishing and polling counters. The worker sleeps 15 s between ticks and does no polling when the outbox is empty.
