# 0019 — Off-site encrypted backups, a public status page, and Workers AI

- **Status:** deployed and live (status + AI) · R2 backup binding waits on the account enabling R2
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.0.0
- **Roadmap:** R-28
- **Files:** `edge/src/ops.js`, `edge/src/index.js`, `edge/wrangler.toml`, `edge/test/ops.test.js`, `bridge/edge.py`, `bridge/backup.py`, `bridge/watchdog.py`, `bridge/mcp.py`, `bridge/app.py`, `bridge/ui.py`

## Why

Three things a phone cannot do for itself: survive its own loss, report that it is alive when
it is not, and run a model without burning battery. All three belong at the edge.

## How

**Off-site backup.** After each verified local archive, the phone uploads it to
`POST /backup?name=…`; the Worker encrypts with AES-GCM (`BACKUP_KEY`, 12-byte IV prepended)
and stores `backups/<name>.enc` in R2. An index of the last 30 lives in KV and older objects
are deleted. `GET /backup?name=…` decrypts and returns the exact bytes — the restore path is
tested (`backup round-trips through encryption`).

**Heartbeat + public status.** Every watchdog loop (5 min) the phone posts counts, GOWA state
and the last off-site archive to `POST /heartbeat`; `GET /status` renders an Arabic page
(«يعمل» / «متوقف عن الإرسال» + last beat age + backup line) with no secrets and no login.

**Workers AI.** `POST /ai/transcribe` (whisper) and `POST /ai/caption` (llava) take raw bytes
and return text. The phone exposes them as MCP tools so the agent can turn a Telegram voice
note or photo into copy without local inference.

Everything is optional: with `EDGE_URL`/`EDGE_TOKEN` unset, the CRM behaves exactly as before.

## Verify

```bash
cd edge && npm test          # 23 tests: round-trip, auth, status, retention, AI errors
python3 -m unittest bridge.tests.test_edge   # 5 client tests + 2 brand tests
```

Measured live from the phone, over the tailnet, through MCP: `crm_transcribe_audio` on a
42 KB mp3 answered in **2.9 s** (`@cf/openai/whisper`), `crm_caption_image` on a PNG in
**3.9 s** (`llama-4-scout`) with `{description, hashtags}`, `crm_edge_status` reported
`version 0.2.0` and `status 200`, and `/status` rendered «يعمل · قبل 0 دقيقة». The off-site
upload answered `501 R2 binding BACKUPS is missing` — the expected state until R2 is enabled.

Measured in the real Workers runtime (`wrangler dev --local`, workerd with R2/KV emulation):
a 20 KB payload encrypted to 20,028 bytes (+12 IV, +16 tag), downloaded byte-identical
(sha256 match), heartbeat flipped `/status` to «يعمل · آخر نبضة قبل 0 دقيقة», and a wrong token
returned 401. Then end-to-end from the phone through a temporary SSH tunnel: a real 41 KB,
44-post archive uploaded (41,199 packed), the heartbeat accepted, and both archives listed by
`/backup`. Workers AI answers `Binding AI needs to run remotely` in local mode — expected, and
proof that the error path is explicit rather than silent.

## Limits

- **R2 is still off**: `wrangler r2 bucket create crm-backups` answers
  `10042 Please enable R2 through the Cloudflare Dashboard`, so the binding is commented out in
  `wrangler.toml` and `/backup` returns 501. Everything else (`/health`, `/heartbeat`, `/status`,
  `/ai/*`) is live on `https://edge-mcp.ncecpmo.workers.dev`. Uncomment the binding and redeploy
  once R2 is enabled.
- Workers AI free allocation is 10,000 neurons/day and some models now require the paid plan;
  a refusal is surfaced verbatim (`model requires Workers Paid`) instead of a silent failure.
- The status page is public by design and therefore contains counts only — never content,
  phone numbers or tokens.
- Encryption key loss = backups unreadable. Keep `BACKUP_KEY` in a password manager.

## Links

- `docs/EDGE-MCP.md`
- [0016 — backups and watchdog](0016-backups-and-watchdog.md)
