# 0010 — The installer owns Tailscale, not the reader

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.2.0
- **Roadmap:** R-19
- **Files:** `scripts/install.sh`, `docs/SETUP-FROM-ZERO.md`

## Why

Every manual step in a setup guide is a step someone skips. Tailscale was the worst one:
the stack worked on loopback, the developer opened a random port to the internet, and the
guide "worked" while quietly teaching the wrong architecture. The node, the login, the
`serve` publish and the `--statedir` flag are all mechanical — they belong in the installer.

## How

`scripts/install.sh` gained three pieces:

| Piece | What it does |
|---|---|
| `install_tailscale` | reads `pkgs.tailscale.com/stable/?mode=json`, picks the tarball for the machine's arch, installs `tailscale` + `tailscaled` into `bin/` |
| `tailscale_unit` | writes a runit unit (Termux) running userspace networking with **`--state` + `--statedir`**, state under `var/`, plus a resolver file for Android |
| `tailscale_login` | starts `tailscale up --hostname …` in the background, reads the `https://login.tailscale.com/a/…` link from its output and prints it, then tells the reader to run `--finish` |

`--finish` publishes the UI (`serve --bg --https=443 http://127.0.0.1:8085`) and prints the
closing checklist. New flags: `--tailscale` (do it standalone) and `--skip-tailscale`
(loopback-only machine).

The `summary` block is now a truth table — what the installer completed (`[x]`) and the four
things only a human can do (`[ ]`): WhatsApp QR, Tailscale login, model key, push channel.

`docs/SETUP-FROM-ZERO.md` is the ordered guide for a developer who has never seen the repo:
F-Droid prerequisites, what each installer step produces, the Tailscale loop, GOWA pairing,
PicoClaw onboarding, push notifications, a health sweep, and the manual residue.

## Verify

```bash
bash -n scripts/install.sh
bash scripts/install.sh --dry-run --prefix /tmp/inst-dry   # prints the plan, touches nothing
# on a real phone:
bash scripts/install.sh --finish
tailscale serve status        # https://<host>.<tailnet>.ts.net → 127.0.0.1:8085
```

## Limits

- The login link expires; the guide says to re-run `--finish` after approving, not to keep
  the URL.
- Non-Termux installs get printed `tailscaled` instructions instead of a unit — the script
  does not guess between systemd, OpenRC and containers.
- Tailscale binaries are downloaded from the official stable channel; a locked-down network
  needs to mirror them and set `CRM_TS_MIRROR` (not implemented yet).

## Links

- `docs/SETUP-FROM-ZERO.md`
- [0007 — the stack on the phone](0007-stack-on-the-phone.md)
