# 0007 — The stack moved to the phone

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.0.0
- **Roadmap:** R-16
- **Files:** `scripts/phone-start.sh`, `docs/features/0006-phone-start-script.md`

## Why

The project's premise is a CRM that lives on the owner's phone, not on a rented server. The
server deployment was a working detour (the phone was offline when the stack was built), but
it left the owner with two machines to reason about, and it kept the phone's old EspoCRM
stack running for nothing.

## How

Everything the server ran as four containers now runs as three runit services on the phone,
plus the infrastructure that was already there:

| Server | Phone |
|---|---|
| `crm-gowa` container (image 9.11.0) | `gowa` unit, proot binary 9.10.0, `127.0.0.1:3000` |
| `crm-app` (python:3.12-alpine) | `crm` unit, Termux python 3.14, `127.0.0.1:8085` |
| `crm-picoclaw` | `picoclaw` unit, aarch64 binary, `127.0.0.1:18790` |
| `crm-node` (tailscale + serve) | the phone's own tailscaled + `tailscale serve` |

Cutover, in order:

1. **Stop the server gateway first** — the WhatsApp session is a single writer; copying its
   `storages/` while it runs risks a torn sqlite file.
2. Copy `storages/` (7.3 MB) to `~/gowa-espo/storages`, keeping the old directory as
   `storages.bak-*`. The paired session survived the move: the phone reports
   `is_logged_in: true` with the same JID, **no QR scan**.
3. Copy the code (`bridge/`, `scripts/`, `config/`) and data (`crm.db` 200 KB, media) —
   `crm.db` keeps all 42 posts, 40 of them published.
4. Rewrite the bridge env for the phone: `CRM_DB_PATH`, `MEDIA_DIR`, `BRIDGE_PORT=8085`,
   `BRIDGE_ENV_FILE`, and the same token so PicoClaw keeps its existing MCP entry.
5. Add the `crm` and `picoclaw` runit units and point PicoClaw's MCP URL at `:8085` — the
   server used `:8086`, and that one-line difference is the whole reason a stale config
   fails silently.
6. PicoClaw's config carried `/data/workspace` (its container home). Rewriting those paths
   to the Termux home was required; without it the gateway exits with
   `mkdir /data/workspace: permission denied`.
7. `docker compose down` on the server — containers removed, **volumes kept** as a rollback.

`scripts/phone-start.sh` (deployed as `~/start.sh`) encodes the order and the health waits:
infrastructure → gowa → crm → picoclaw, `restart` and `stop` subcommands, and the retired
EspoCRM units listed but never started.

## Verify

```bash
sh ~/start.sh status
#  sshd up  rtunnel up  tailscaled up  crond up
#  gowa up  crm up  picoclaw up
#  mariadb down  php-fpm down  nginx down  bridge down

curl -s 127.0.0.1:8085/health      # {"ok": true, "crm": true}
curl -s 127.0.0.1:18790/health     # {"status":"ok",...}
curl -su "$GOWA_USER:$GOWA_PASSWORD" -H 'X-Device-Id: primary' \
     127.0.0.1:3000/app/status     # is_logged_in: true, jid 966502369637
```

MCP on the phone returns the same 16 tools, and `content_insights` answers with real data
(video: 16 views) — the DB moved intact.

## Limits

- The phone has ~800 MB free with the stack running; a large media upload is the first thing
  that will hurt, so the 20 MB media cap matters more here than it did on the server.
- Android may freeze the stack despite the wake lock; the runit units restart, and
  `~/start.sh status` is the one honest answer to "is it up?".
- Tailscale on the phone is a userspace node: no inbound LAN access, tailnet only.
- The server's docker volumes still hold the pre-move session; delete them only after a week
  of stable phone operation.

## Links

- `docs/ANDROID-BACKGROUND.md`
- `docs/DEPLOY.md`
- CHANGELOG: 3.0.0
