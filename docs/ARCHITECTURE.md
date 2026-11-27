# Architecture

Three processes, one host, no broker, no container required.

```
┌──────────────────────────── phone / small server ────────────────────────────┐
│                                                                              │
│  PicoClaw (agent)  ── MCP over HTTP ──►  CRM bridge :8085                     │
│       │                                     │  /ui   Arabic SSR UI          │
│       │                                     │  /mcp  JSON-RPC (15 tools)     │
│       └── Telegram channel                  │  /health, /status             │
│                                             │                               │
│  GOWA :3000 ── HMAC webhook ───────────────►│  outbox worker (same process)  │
│       │                                     ▼                               │
│       └── WhatsApp Web session         SQLite: crm.db  + media/             │
│                                         (WAL, one writer)                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Processes and ports

| Port | Process | Bind | Purpose |
|---|---|---|---|
| 8085 | `bridge/app.py` | `127.0.0.1` | Arabic UI, MCP server, webhook receiver, outbox worker |
| 3000 | `gowa rest` | `127.0.0.1` | WhatsApp session, send API, device/QR endpoints |
| 18790 | `picoclaw gateway` | `127.0.0.1` | Agent runtime (Telegram, MCP client) |
| 443 | `tailscale serve` | tailnet | TLS termination for the UI, no public exposure |

Everything binds to loopback. Remote access is the tailnet's job, not the app's.

## The CRM process

One `ThreadingHTTPServer` plus one worker thread:

- **HTTP handler** — Basic auth for `/ui`, bearer for `/mcp`, HMAC for `/webhook/gowa`.
- **Worker loop** — drains the `outbox` table, publishes due posts, polls channel counters, imports the channel archive.
- **SQLite** — single file, WAL mode, `busy_timeout` set; all writes go through `CrmClient` / `Store`.

The worker and the handler share one store; writes are serialised with a lock. There is no second writer, so no cross-process locking problem.

## Data model (SQLite)

| Table | Rows it holds |
|---|---|
| `crm_posts` | content items: status, body, media, schedule, publish ids, counters |
| `crm_stats` | per-post daily snapshots (views/forwards/reactions) |
| `crm_contacts`, `crm_deals`, `crm_activities` | CRM side |
| `crm_messages` | inbound/outbound DMs linked to contacts |
| `crm_notifications` | in-app alerts (published, failed, unread DMs) |
| `crm_channel_info` | cached channel name, jid, subscribers, invite |
| `crm_chat` | transcript of the PicoClaw chat panel |
| `outbox` | pending sends with attempt counter and backoff |
| `crm_seen` | webhook de-duplication by message id |

Content states: `draft → scheduled → publishing → published`, plus `failed` (cancelled or permanently failed, kept for the archive).

## Flows

**Inbound DM**

1. GOWA posts to `/webhook/gowa` with `X-Hub-Signature-256`.
2. The bridge verifies the HMAC, de-duplicates by message id, upserts the contact, stores the message, opens a notification.
3. If the contact has an open deal, the message is attached to it.

**Publishing**

1. A human schedules a post (or presses publish) in the UI; the MCP agent can only create drafts.
2. The post becomes `scheduled` with `scheduled_at`; the worker picks it up when due.
3. The worker claims it (`publishing`), sends through GOWA (`/send/message`, `/send/image`, …), stores `message_id`, marks `published`.
4. Failure: retry with backoff (30 s → 6 h, max 5); permanent failures (a poll on a channel, for example) are recorded with the GOWA error and need a human decision.

**Archive and metrics**

- On boot and every `BRIDGE_CHANNEL_SYNC_INTERVAL`, the worker pulls the newest channel messages and stores new ones (idempotent by `message_id`).
- Counters come from `/newsletter/messages` and `/newsletter/message-updates`; daily snapshots feed the sparkline.

## Decisions worth knowing

- **SQLite over Postgres** — one user, one writer, a phone; a database server would cost more RAM than the whole app.
- **Server-rendered HTML over a SPA** — the UI must survive a weak phone and a bad connection; no framework, no hydration, one 3.5 KB progressive-enhancement script.
- **Outbox over in-memory retries** — a phone gets killed by the OS; the queue must survive restarts.
- **Human approval by default** — an agent that can publish to a public channel unattended is a liability; `AGENT_CAN_PUBLISH=1` exists for people who accept that risk.
- **No media transcoding** — files are forwarded as-is under a 20 MB cap; WhatsApp does the rest.

## Failure boundaries

| Failure | Behaviour |
|---|---|
| GOWA offline | Publishes fail into the outbox with backoff; the UI keeps working on local data |
| WhatsApp logged out | Sends return 401; a notification tells the owner to re-pair |
| Agent provider down | PicoClaw retries; the CRM is unaffected |
| Disk full | SQLite raises; the API returns 500 and the log names the file |
