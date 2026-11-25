# GOWA ⇄ EspoCRM Bridge (Termux / Android, no root, no Docker)

Run **WhatsApp** (via [GOWA](https://github.com/aldinokemal/go-whatsapp-web-multidevice))
and **EspoCRM** side by side on a low-end Android phone, with a two-way bridge
that logs incoming messages into the CRM and publishes CRM records to WhatsApp
Channels.

Built and verified on a **Huawei P Smart 2019** (Kirin 710, 2.69 GB RAM,
Android 9 / EMUI 9.1) inside Termux, with no root and no Docker.

> العربية: [README.ar.md](README.ar.md)

---

## What it does

**Inbound (WhatsApp → CRM)**

- Incoming DM → finds or creates the `Contact` by phone number and appends the
  message to the record timeline.
- New post in a followed Channel → stored as a `WhatsAppChannelPost` record
  with body, media type, timestamp and server ID.
- Channel counters (views / forwards / reactions) → updated on the same record.

**Outbound (CRM → WhatsApp)**

- A `WhatsAppChannelPost` moved to **Ready to Publish** is posted to the Channel
  JID. Triggered instantly by an EspoCRM `afterSave` hook, and re-checked by a
  60 s poller as a safety net.
- Any `Contact` / `Lead` can be messaged through the same webhook.

**Durability** — every publish goes through a SQLite outbox with retries and
backoff, so a logged-out session or a sleeping phone never silently drops a post.

**MCP** — the same process serves a Model Context Protocol endpoint at
`POST /mcp`, so an AI client can search CRM records, schedule or publish channel
posts, read a channel, and send WhatsApp messages. See [docs/MCP.md](docs/MCP.md).

---

## Verified on the reference device

| Component | Version | Notes |
|-----------|---------|-------|
| GOWA | 9.10.0 | custom **static musl + cgo** build, 32 MB |
| EspoCRM | 10.1.4 | PHP 8.5.13, FPM `ondemand`, 4 children |
| MariaDB | 13.1.2 | 48 MB buffer pool, `performance_schema=OFF` |
| nginx | 1.31.10 | EspoCRM on :8081 |
| Python | 3.14 | bridge, **stdlib only** — no pip packages |
| proot | 5.x | bind-mounts `/etc/resolv.conf` + CA bundle only |

Measured idle footprint of the whole stack: **~150 MB**; peak ~450 MB of the
~600 MB Android leaves free.

---

## Architecture

```
WhatsApp ──▶ GOWA :3000 ──webhook(HMAC)──▶ bridge :8085 ──X-Api-Key──▶ EspoCRM :8081
                 ▲                              │                        │
                 └────── /send/message ─────────┘                        │
                                                              afterSave hook + 60s poll
```

Full detail, including why the bridge owns idempotency and durability:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Quick start

### 1. Build the GOWA binary (on any machine with Docker)

The official `linux-arm64` release **does not run on Termux** — it is linked
against glibc. This produces a static musl binary instead:

```bash
./scripts/build-gowa-arm64.sh 9.10.0 ./whatsapp
scp ./whatsapp <phone>:~/gowa-espo/bin/whatsapp
```

### 2. Install the stack on the phone

```bash
# inside Termux
git clone <this repo> ~/gowa-espocrm-bridge
cd ~/gowa-espocrm-bridge
bash scripts/install-termux.sh
```

This installs packages, initialises MariaDB with low-RAM tuning, configures
PHP-FPM + nginx, downloads EspoCRM, installs the custom entity, creates the
least-privilege API user, and registers every service under runit.

### 3. Link WhatsApp

```bash
curl -X POST localhost:3000/devices -H 'Content-Type: application/json' \
  -d '{"device_id":"primary","webhook_url":"http://127.0.0.1:8085/webhook/gowa"}'

curl -s localhost:3000/devices/primary/login
# → results.qr_link : download it and scan from WhatsApp → Linked devices
```

### 4. Point the bridge at your Channel

```bash
# ~/gowa-espo/.env
NEWSLETTER_JIDS=120363024512399999@newsletter
```

```bash
sv restart bridge
```

### 5. Health check

```bash
bash scripts/start-all.sh
curl -s localhost:8085/health | python3 -m json.tool
```

---

## Configuration

Everything lives in one file, `~/gowa-espo/.env` (mode `600`, git-ignored).
See [.env.example](.env.example) for the full list.

| Key | Purpose |
|-----|---------|
| `GOWA_BASE_URL` | GOWA REST base (loopback) |
| `GOWA_WEBHOOK_SECRET` | HMAC key for `X-Hub-Signature-256` |
| `BRIDGE_TOKEN` | bearer token EspoCRM presents |
| `ESPO_BASE_URL` / `ESPO_API_KEY` | CRM endpoint + API-user key |
| `NEWSLETTER_JIDS` | channels to monitor; empty = all followed |
| `DEFAULT_COUNTRY_CODE` | normalise local numbers |
| `BRIDGE_POLL_INTERVAL` | publish poll seconds (default 60) |
| `BRIDGE_CHANNEL_SYNC_INTERVAL` | channel backfill seconds (default 300) |

---

## The custom CRM entity

`WhatsAppChannelPost` — subject, channel JID/name, message ID, server ID, body,
media type/URL, posted time, views/forwards/reactions, publish status.

```
New ──▶ Ready to Publish ──▶ Published
              └──▶ Failed (lastError attached)
```

Definitions live in [espocrm-custom/](espocrm-custom/) as plain JSON + PHP, so
they are reviewable and versioned instead of clicked together in a UI.

---

## Operations

```bash
sv status mariadb php-fpm nginx gowa bridge      # service states
tail -f $PREFIX/var/log/sv/bridge/current        # bridge log
tail -f $PREFIX/var/log/sv/gowa/current          # GOWA log
curl -s localhost:8085/health                    # dependency + queue health
```

Services survive shell exit and reboot (runit + `~/.termux/boot/00-server.sh`).
EMUI needs three extra permissions or Android kills Termux overnight — see
[docs/EMUI-BATTERY.md](docs/EMUI-BATTERY.md).

---

## Security model

- GOWA, EspoCRM and the bridge bind **127.0.0.1 only**.
- GOWA webhooks are authenticated with HMAC-SHA256 over the raw body.
- EspoCRM → bridge calls require a bearer token, compared in constant time.
- The bridge uses a dedicated **API user** with a role limited to
  Contact / Lead / Case / Account / WhatsAppChannelPost / Note — never the
  admin password.
- `.env`, WhatsApp session storage, SQLite databases and dumps are git-ignored.

Expose nothing directly to the internet. For remote access put Tailscale or an
SSH tunnel in front.

---

## Known limitations

- **Publishing requires channel admin rights.** A follower account can monitor
  and log a channel but WhatsApp refuses to post on its behalf.
- **`views_count` is admin-only.** Non-admin accounts receive 0 from WhatsApp.
- **Live counter subscriptions are in memory** in GOWA; the bridge re-subscribes
  on start and on every channel-sync tick.
- **EspoCRM Advanced Pack is not used** (it is paid). Instant publishing relies
  on the custom `afterSave` hook; the poller covers hook failures.
- Media is referenced, not mirrored: GOWA runs with `--auto-download-media=false`
  to keep RAM flat. Use `/newsletter/messages/{id}/download` if you need files.
- The scripts were assembled from the exact commands that built the reference
  device, but a from-scratch run on a different Android version may need path or
  package adjustments. Issues and PRs welcome.

---

## Repository layout

```
bridge/              Python service (config, clients, outbox, HTTP, MCP, tests)
espocrm-custom/      Entity metadata, layouts, PHP controller/entity/hook, vhost
scripts/             install-termux.sh, build-gowa-arm64.sh, runit units, tuning
docs/                architecture, API, EMUI battery, troubleshooting
```

Tests (no dependencies): `cd bridge && python3 -m unittest discover -s tests`

---

## License

MIT — see [LICENSE](LICENSE).
