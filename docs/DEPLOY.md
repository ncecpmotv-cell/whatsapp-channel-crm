# Deployment

Tested on **Termux (Android, aarch64)** and **Debian/Ubuntu (amd64, arm64)**. Root is not required on either.

## One script

```bash
git clone https://github.com/ncecpmotv-cell/whatsapp-channel-crm
cd whatsapp-channel-crm
bash scripts/install.sh
```

What it does:

1. Detects the platform and architecture (Termux installs its own packages).
2. Downloads the **latest** GOWA release (`whatsapp_<ver>_linux_<arch>.zip`) and PicoClaw release (`picoclaw_Linux_<arch>.tar.gz`).
3. Copies or clones the CRM into `~/.whatsapp-crm/app`.
4. Generates `etc/crm.env` and `etc/gowa.env` with random secrets (mode 600).
5. Runs `picoclaw config reset` and registers the CRM as an MCP server (`tools.mcp.servers.crm`).
6. Writes `bin/crmctl` (start/stop/restart/status/logs) and, where possible, a runit or systemd unit.
7. Starts GOWA, the bridge and PicoClaw, then prints the URL and token location.

```
~/.whatsapp-crm/
├── app/            # this repo (bridge/, scripts/)
├── bin/            # gowa, picoclaw, crmctl
├── etc/            # crm.env, gowa.env  (secrets, 600)
├── picoclaw/       # config.json, workspace/
└── var/            # crm.db, media/, static/, log/
```

### Options

| Flag | Effect |
|---|---|
| `--prefix DIR` | Install somewhere other than `~/.whatsapp-crm` |
| `--port N` | Bridge port (default 8085) |
| `--skip-gowa`, `--skip-picoclaw` | Install only part of the stack |
| `--no-service` | Do not write a runit/systemd unit |
| `--from-local DIR` | Install from a local checkout instead of GitHub |
| `--dry-run` | Print the plan, change nothing |

Environment: `GOWA_PORT` (3000), `PICO_PORT` (18790), `CRM_REPO`.

## Pair WhatsApp

```bash
bash scripts/install.sh --qr
```

The QR is written to `~/.whatsapp-crm/var/whatsapp-qr.png`; scan it from **WhatsApp → Linked devices**. If GOWA is not answering yet, open `http://127.0.0.1:3000` and pair from the built-in UI. Once paired, set the channel:

```bash
# etc/crm.env
NEWSLETTER_JIDS=1203xxxxxxxxxxxxxx@newsletter
```

Restart the bridge (`crmctl restart`) and press **مزامنة أرشيف القناة** on the Channel page.

## Services

**Termux (with `termux-services`)**

```bash
pkg install termux-services
sv-enable crm        # installer wrote $PREFIX/var/service/crm/run
```

**systemd (root)**

The installer writes `/etc/systemd/system/whatsapp-crm.service` when run as root and enables it. Otherwise:

```bash
sudo install -m 644 /dev/stdin /etc/systemd/system/whatsapp-crm.service <<'EOF'
[Unit]
Description=WhatsApp Channel CRM
After=network-online.target
[Service]
Type=forking
User=%i
ExecStart=%h/.whatsapp-crm/bin/crmctl start
ExecStop=%h/.whatsapp-crm/bin/crmctl stop
[Install]
WantedBy=multi-user.target
EOF
```

**No service manager** — `~/.whatsapp-crm/bin/crmctl start` (survives until the process is killed; Android needs the battery settings in [`ANDROID-BACKGROUND.md`](ANDROID-BACKGROUND.md)).

## Private remote access (Tailscale)

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8085
```

Then open `https://<machine>.<tailnet>.ts.net/ui` from any device in the tailnet. Nothing is exposed to the public internet; no ports are opened.

## Upgrade

```bash
bash scripts/install.sh --upgrade
```

Re-downloads the latest GOWA and PicoClaw releases, refreshes the CRM checkout, and restarts the stack. Your data (`var/crm.db`, `var/media`, `etc/*.env`) is untouched.

## Backup and restore

```bash
# online-safe copy (WAL included) using SQLite's own backup API
python3 - <<'PY'
import os, sqlite3
home = os.path.expanduser("~/.whatsapp-crm")
src = sqlite3.connect(os.path.join(home, "var", "crm.db"))
dst = sqlite3.connect("/tmp/crm-backup.db")
src.backup(dst); dst.close(); src.close()
PY

tar -czf crm-backup-$(date +%F).tar.gz -C ~/.whatsapp-crm var/crm.db var/media etc
```

Restore: stop the stack, put `crm.db` and `media/` back, start it.

## Uninstall

```bash
bash scripts/uninstall.sh           # stop, keep data
bash scripts/uninstall.sh --purge   # stop and delete the install directory
```
