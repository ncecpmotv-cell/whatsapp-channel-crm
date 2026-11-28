# 0019 — Off-site encrypted backups, a public status page, and Workers AI

- **Status:** code shipped and tested · deployment needs the owner's Cloudflare auth
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

Measured locally: a 40 KB archive encrypts to ~40 KB, decrypts byte-identical; the status page
flips to «متوقف عن الإرسال» once the heartbeat is an hour old.

## Limits

- **Not deployed yet**: `wrangler deploy` needs the account that owns `edge-mcp`; the R2 bucket
  and KV namespace must exist first (`wrangler r2 bucket create crm-backups`,
  `wrangler kv namespace create STATUS`, then paste the id in `wrangler.toml`).
- Workers AI free allocation is 10,000 neurons/day and some models now require the paid plan;
  a refusal is surfaced verbatim (`model requires Workers Paid`) instead of a silent failure.
- The status page is public by design and therefore contains counts only — never content,
  phone numbers or tokens.
- Encryption key loss = backups unreadable. Keep `BACKUP_KEY` in a password manager.

## Links

- `docs/EDGE-MCP.md`
- [0016 — backups and watchdog](0016-backups-and-watchdog.md)
