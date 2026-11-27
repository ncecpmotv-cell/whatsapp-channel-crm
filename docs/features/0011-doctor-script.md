# 0011 — `doctor.sh`: one command that tells the truth

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.3.0
- **Roadmap:** R-20
- **Files:** `scripts/doctor.sh`, `docs/SETUP-FROM-ZERO.md`

## Why

After building the stack by hand, "is everything really up?" had five answers: `crmctl status`,
three `/health` curls, a Tailscale command, and a database query. A developer following the
guide cannot tell a working install from a half-working one, and neither could I without
typing all five.

## How

`scripts/doctor.sh` — read-only, no arguments needed, exit code 1 if a required check fails:

| Section | Checks |
|---|---|
| Toolchain | `python3`, `curl`, and the real binary paths (GOWA ships as `whatsapp`, PicoClaw may live in `~/pico/bin`) |
| Services | runit units `gowa`, `crm`, `picoclaw` (+ `sshd`, `tailscaled` as warnings) or `crmctl status` on installer layouts |
| Endpoints | `/health` on 8085, 3000, 18790 |
| WhatsApp | `/app/status` with the env credentials → `is_logged_in` |
| CRM | MCP `tools/list` count (≥16), UI answers with the token |
| Agent | skills installed, `"crm"` present in `config.json` |
| Tailscale | node identity and the `https://…` serve entry, run through `proot` on Android (the static Go binary dies with `SIGSYS` without it) |
| Push | `termux-api` present, `push.enabled` in `/health` |

Two layouts are detected: runit (this phone) and the installer's `~/.whatsapp-crm`. Warnings
do not fail the run; failures do.

## Verify

On the phone, after the migration:

```
Toolchain ✓✓✓✓✓ · Services ✓✓✓✓✓ · Endpoints ✓✓✓
WhatsApp ✓ · CRM ✓✓ · Agent ✓✓ · Tailscale ✓✓ · Push ✓✓
22 passed · 0 failed · 0 warnings
```

Before the fixes it reported four false alarms — binary names, a JSON spacing bug in the grep,
and Tailscale crashing without `proot` — each fixed in the script, not in the environment.

## Limits

- It cannot test the browser path: an `Origin` problem looks healthy from loopback. The 403
  detail and `origin_guard` in `/health` cover that case.
- It assumes the default ports; a custom install needs `GOWA_PORT`/`BRIDGE_PORT`/`PICO_PORT`.
- Read-only by design: it never restarts a unit or repairs a config.

## Links

- `docs/SETUP-FROM-ZERO.md` §6
- [0010 — installer owns Tailscale](0010-installer-tailscale.md)
