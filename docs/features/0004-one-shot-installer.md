# 0004 — One-command installer (GOWA + PicoClaw + CRM)

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.0.0
- **Roadmap:** R-04
- **Files:** `scripts/install.sh`, `scripts/uninstall.sh`, `docs/DEPLOY.md`

## Why

Three processes with three configuration formats and three update paths is where new users
give up. Installing by hand meant: build or download GOWA, invent a shared secret, write
`gowa.env`, write `crm.env`, hand-wire the MCP server into PicoClaw, then remember the start
order. The installer turns that into one command that is also the upgrade command.

## How

1. Detect Termux vs Linux and the architecture (`arm64/armv7/armv6/amd64`).
2. Ask GitHub for the **latest release tag** of GOWA and PicoClaw, then download the matching
   asset and extract the binary by size (release zips name the payload after the platform).
3. Clone (or copy) the CRM into `$ROOT/app`.
4. Generate `etc/crm.env` and `etc/gowa.env` with random secrets, mode 600.
5. `picoclaw config reset` to get a valid default config, then
   `picoclaw mcp add crm <url> -t http -H "Authorization: Bearer …"` — the CLI writes the
   correct `tools.mcp.servers.crm` shape, which a hand-written config gets wrong.
6. Write `bin/crmctl` (start/stop/restart/status/logs) and a runit or systemd unit when one
   is available. `crmctl` matches processes by full path so it cannot adopt an unrelated
   `app.py`, and it refuses to start a second PicoClaw gateway.

`--upgrade` re-runs steps 1–3 and restarts; data is never touched.

## Verify

```bash
bash -n scripts/install.sh
bash scripts/install.sh --dry-run --prefix /tmp/x        # prints the plan, touches nothing
GOWA_PORT=13000 bash scripts/install.sh --prefix /tmp/t2 --port 18086 --from-local . --no-service
# → crm: {"ok": true, "crm": true} · gowa: up (http 401) · pico: up
```

Also verified from the public repo (`--skip-gowa --skip-picoclaw`), which exercises the
clone path: UI answered 200 with the generated token.

## Limits

- Tested on Termux aarch64 and Debian/Ubuntu; other distros work only if `curl/unzip/tar`
  exist.
- No automatic WhatsApp pairing: the QR must be scanned by a human (`--qr`).
- Model and Telegram credentials are deliberately left to `picoclaw onboard`, because they
  are account-specific secrets.

## Links

- `docs/DEPLOY.md`
- `docs/PAIRING-GOWA.md`
- CHANGELOG: "One-shot installer…"
