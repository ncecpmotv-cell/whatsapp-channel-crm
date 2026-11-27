# Troubleshooting

Every entry below is a failure that actually happened while building this, with the fix that worked.

## Install

**`missing 'unzip'` / `missing 'curl'`** — on Debian: `sudo apt install -y unzip curl python3`. On Termux the installer runs `pkg install` itself.

**`unsupported architecture`** — only arm64, armv7, armv6 and amd64 have prebuilt GOWA/PicoClaw releases. On anything else, build GOWA from source and pass `--skip-gowa`.

**`no binary inside whatsapp_...zip`** — release zips name the payload after the platform (`linux-arm64`), not `whatsapp`. The installer already searches by size; if you edited it, restore that `find … -size +1M` step.

**Everything is "down" right after install** — the first start downloads assets and initialises WAL. Check `~/.whatsapp-crm/var/log/*.log`, then `crmctl start` again.

## WhatsApp pairing

**QR never appears** — GOWA answers `401` until you authenticate: `curl -u crm:$GOWA_PASSWORD http://127.0.0.1:3000/app/login -o qr.png`. Credentials are in `etc/gowa.env`.

**`Logged out` / sends fail with 401** — the WhatsApp session expired (new phone, WhatsApp Web logout, or a restore from backup). Re-pair with `install.sh --qr`; the CRM data is unaffected.

**Publishing fails with `479`** — the content type is a poll. WhatsApp Channels do not support polls; the UI blocks them and the API returns a permanent error instead of retrying forever.

## The UI

**Page looks unstyled** — `app.css` is missing. It is generated: run `python3 scripts/build_static.py`, or just restart the bridge (it writes the stylesheet at boot). `GET /static/app.css` must return 200.

**CSS/JS changes do not reach the phone** — asset URLs carry `?v=<hash>`; if you serve a stale copy, the HTML itself is cached. Hard-refresh once. Never remove the version query: a bare filename plus `immutable` locks a browser to the old file for a week.

**A control is squeezed to a sliver** — a flex child is winning the width fight (usually a `button { width: 100% }` rule from the mobile block). Give the button `width: auto; flex: 0 0 auto` and the input `flex: 1; min-width: 0`.

**Arabic digits or dates look mixed** — format timestamps through `fmt_ts()` only; it applies the `TZ_OFFSET` from the config and one consistent pattern.

## Data

**A post is stuck in `publishing`** — the worker died mid-send. It is recovered on the next tick (claim is idempotent); if it stays, `UPDATE crm_posts SET status='scheduled' WHERE id='…'` and let the worker retry.

**Counters are zero** — either the channel archive was never imported (`/ui/channel` → **مزامنة أرشيف القناة**) or GOWA is not authenticated for that channel.

**`database is locked`** — two writers. Only one bridge process may own `crm.db`; check `pgrep -af bridge/app.py` and kill the stray one.

**Media 404** — the file was removed or never written. `GET /ui/media/<name>` only serves `MEDIA_NAME_RE` names from `MEDIA_DIR`; check `var/media` and `MEDIA_DIR` in `etc/crm.env`.

## Access

**401 in the browser but curl works** — the browser is still sending an old password. Close the tab, or use a private window; Basic credentials are cached per origin.

**429 Too Many Requests** — 10 failed logins from the same IP within 5 minutes. Wait 5 minutes, or restart the bridge to clear the in-memory counter.

**Tailscale URL returns 502** — `tailscale serve` is pointing at the wrong port. `tailscale serve status`, then re-run `tailscale serve --bg --https=443 http://127.0.0.1:8085`.

**Android kills the stack overnight** — battery optimisation, not the app. See [`ANDROID-BACKGROUND.md`](ANDROID-BACKGROUND.md).

## Agent (PicoClaw)

**The agent has no CRM tools** — the MCP server is not registered:

```bash
PICOCLAW_HOME=~/.whatsapp-crm/picoclaw ~/.whatsapp-crm/bin/picoclaw mcp list
PICOCLAW_HOME=~/.whatsapp-crm/picoclaw ~/.whatsapp-crm/bin/picoclaw mcp test crm
```

`mcp add` writes to `tools.mcp.servers.<name>`; a hand-written top-level `mcp` key is ignored.

**Agent answers "unauthorized"** — the bearer token in `config.json` no longer matches `BRIDGE_TOKEN`. Re-run the `mcp add` command from the installer.
