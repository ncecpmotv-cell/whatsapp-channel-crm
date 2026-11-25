# Architecture

## Ports and processes

| Port | Process | Bound to | Purpose |
|------|---------|----------|---------|
| 3000 | `whatsapp rest` (GOWA) | 127.0.0.1 | WhatsApp REST API + webhook emitter |
| 8081 | nginx → php-fpm :9000 | 127.0.0.1 | EspoCRM UI + REST API |
| 8085 | `python3 app.py` (bridge) | 127.0.0.1 | Inbound webhooks, outbound publishing |
| 3306 | mariadbd | 127.0.0.1 | EspoCRM database |
| 8080 | nginx default vhost | 0.0.0.0 | Termux landing page (unrelated) |

Everything except the nginx default vhost is loopback-only. No port is exposed
to the LAN or the internet; remote access is expected to go through Tailscale
or an SSH tunnel.

## Data flow

```
                    ┌──────────────────────────┐
   WhatsApp ───────▶│  GOWA (whatsmeow, Go)    │
   (multi-device)   │  127.0.0.1:3000          │
                    └───────┬──────────────────┘
      new DM / channel post │ POST /webhook/gowa
      + newsletter counters │ X-Hub-Signature-256 (HMAC-SHA256)
                            ▼
                    ┌──────────────────────────┐        ┌───────────────────┐
                    │  Bridge (Python stdlib)  │◀──────▶│  SQLite           │
                    │  127.0.0.1:8085          │        │  seen + outbox    │
                    └───────┬──────────────────┘        └───────────────────┘
                            │ X-Api-Key (least-privilege user)
                            ▼
                    ┌──────────────────────────┐
                    │  EspoCRM 10 (PHP-FPM)    │
                    │  nginx :8081             │
                    │  ├─ Contact / Lead       │
                    │  ├─ Note (timeline)      │
                    │  └─ WhatsAppChannelPost  │
                    └───────┬──────────────────┘
                            │ AfterSave hook (instant)
                            │ + 60 s poller (safety net)
                            ▼
                    POST /webhook/espocrm  (X-Bridge-Token)
                            │
                            ▼
                    GOWA POST /send/message → channel JID / phone
```

## Why the bridge owns three responsibilities

1. **Inbound mapping** — GOWA sends raw WhatsApp payloads; EspoCRM has no idea
   what a `@newsletter` JID is. The bridge translates.
2. **Idempotency** — WhatsApp redelivers, GOWA restarts, the bridge restarts.
   A SQLite `seen` table keyed by WhatsApp message ID makes replays harmless.
3. **Durability** — a publish must survive GOWA being logged out or the phone
   sleeping. The `outbox` table stores intent, retries with linear backoff
   (30 s × attempt, 5 attempts), and only then marks the CRM record `Failed`
   with the last error attached.

## Publishing is triggered twice, on purpose

EspoCRM's Advanced Pack (paid) is the only built-in way to fire an outbound
webhook. Without it, two mechanisms cover the gap:

- **Instant**: `custom/Espo/Custom/Hooks/WhatsAppChannelPost/NotifyBridge.php`
  calls the bridge from `afterSave` when `status` changes to `Ready to Publish`.
- **Durable**: the bridge polls `GET /api/v1/WhatsAppChannelPost` for
  `status = "Ready to Publish"` every 60 s.

The hook can fail (bridge down, timeout); the poller always catches up. Both
paths enqueue into the same outbox, and the unique partial index
`outbox(kind, ref) WHERE status='pending'` prevents double posts.

## Channel monitoring

Two sources, merged:

- **Live**: GOWA forwards new channel posts as ordinary `message` events whose
  `chat_id` ends in `@newsletter`. Counter updates arrive as `newsletter.message`
  events, but only while a `/newsletter/live-updates` subscription is active —
  and those subscriptions live in GOWA's memory, so the bridge re-subscribes on
  every start and every `BRIDGE_CHANNEL_SYNC_INTERVAL`.
- **Backfill**: `GET /newsletter/messages?newsletter_id=…&count=20` every
  `BRIDGE_CHANNEL_SYNC_INTERVAL` seconds catches posts made while the phone was
  asleep or GOWA was restarting.

`views_count` is only reported to channel **admins**; for other accounts
WhatsApp returns 0 and the bridge stores 0.

## Why a custom GOWA build

The official `whatsapp_<v>_linux_arm64.zip` is dynamically linked against
`libc.so.6` and `ld-linux-aarch64.so.1`. Termux uses Android's bionic libc and
has no glibc loader, so the binary fails with `required file not found`.

`CGO_ENABLED=0` is not an option either: GOWA uses `mattn/go-sqlite3`, which
needs cgo, and dies at startup with
`Binary was compiled with 'CGO_ENABLED=0', go-sqlite3 requires cgo`.

The working recipe is upstream's own Alpine/musl build, linked fully static:

```
CGO_ENABLED=1 CC=musl-gcc go build -ldflags '-linkmode external -extldflags "-static"'
```

`scripts/build-gowa-arm64.sh` reproduces it in Docker on any machine.

## Android-specific runtime shims

Two files that exist on every Linux distro and on no Android device:

| Missing | Symptom | Fix |
|---------|---------|-----|
| `/etc/resolv.conf` | `lookup web.whatsapp.com on [::1]:53: connection refused` | proot bind-mounts `~/gowa-espo/etc/resolv.conf` |
| `/etc/ssl/certs/ca-certificates.crt` | `x509: certificate signed by unknown authority` | proot bind-mounts `$PREFIX/etc/tls/cert.pem`, plus `SSL_CERT_FILE` |

`proot` is used for the bind mounts only — no distro, no root, ~10 MB RSS. It
does **not** honour `SIGTERM` from runit, so a restart requires killing the PID
(`sv down` alone leaves the old process alive).
