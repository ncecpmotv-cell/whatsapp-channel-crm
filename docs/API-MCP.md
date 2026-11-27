# HTTP API and MCP tools

Base URL: `http://127.0.0.1:8085` (loopback). Authentication differs per surface:

| Surface | Auth |
|---|---|
| `/ui/**` | HTTP Basic — any username, password = `BRIDGE_TOKEN`; forms also carry a CSRF token |
| `/mcp` | `Authorization: Bearer <BRIDGE_TOKEN>` |
| `/status`, `/hook/publish` | `Authorization: Bearer <BRIDGE_TOKEN>` |
| `/webhook/gowa` | `X-Hub-Signature-256: sha256=<hmac>` over the raw body |
| `/health` | none (minimal: `{"ok": true, "crm": true}`) |

`BRIDGE_TOKEN` lives in `etc/crm.env` (mode 600).

## HTTP endpoints

### `GET /health`

```json
{"ok": true, "crm": true}
```

### `GET /status` — bearer

Queue depth, CRM counters and the monitored channel JIDs.

### `POST /webhook/gowa`

Inbound events from GOWA. Signed with `GOWA_WEBHOOK_SECRET`. Returns `{"ok": true}`; duplicate message ids are ignored.

### `POST /hook/publish` — bearer

Queue a post for immediate publishing.

```bash
curl -s -X POST http://127.0.0.1:8085/hook/publish \
  -H "Authorization: Bearer $BRIDGE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"postId":"<id>"}'
```

### UI routes

| Route | Method | Purpose |
|---|---|---|
| `/ui` | GET | Today's dashboard (counters, scheduled, follow-ups) |
| `/ui/content` | GET | Content list — `?status=draft|scheduled|published|failed&page=N` |
| `/ui/content/new` | POST | Create a post (multipart when media is attached) |
| `/ui/content/edit` | POST | Update title/body; a date also reschedules |
| `/ui/content/schedule` | POST | Schedule (or reschedule) |
| `/ui/content/publish` | POST | Publish now (human decision) |
| `/ui/content/cancel` | POST | Cancel — keeps the record as `failed`/cancelled |
| `/ui/content/restore` | POST | Cancelled → draft |
| `/ui/content/delete` | POST | Purge — cancelled items only |
| `/ui/post/{id}` | GET | Post detail: editor, preview, metrics |
| `/ui/media/{name}` | GET | Authenticated media download/preview |
| `/ui/channel` | GET | Channel info, daily series, top posts |
| `/ui/channel/sync`, `/ui/channel/refresh` | POST | Import archive / refresh channel info |
| `/ui/contacts`, `/ui/deals`, `/ui/metrics`, `/ui/notifications` | GET | CRM surfaces |

## MCP server

JSON-RPC 2.0 at `POST /mcp`. 14 tools:

| Tool | What it does |
|---|---|
| `crm_search` | Search contacts, deals and posts |
| `crm_get` | Fetch one record by id |
| `crm_create_channel_post` | Create a draft (never published directly) |
| `crm_update_channel_post` | Edit a draft (agent cannot set `scheduled` unless `AGENT_CAN_PUBLISH=1`) |
| `content_schedule` | Propose a publishing time; status stays `draft` for human approval |
| `crm_list_ready_posts` | Scheduled posts awaiting their time |
| `channel_info` | Channel name, jid, subscribers, invite |
| `channel_metrics` | Views/forwards/reactions per post and in total |
| `contact_upsert` | Create or update a contact |
| `deal_update` | Create or move a deal |
| `followups_due` | Due follow-ups |
| `wa_send` | Send a DM through GOWA |
| `wa_channel_messages` | Read the channel feed |
| `bridge_health` | Health snapshot for the agent |

Example:

```bash
curl -s http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $BRIDGE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"crm_create_channel_post",
                 "arguments":{"name":"t","channelJid":"<jid>","body":"مسودة من الوكيل"}}}'
```

### Registering it in PicoClaw

```bash
PICOCLAW_HOME=~/.whatsapp-crm/picoclaw ~/.whatsapp-crm/bin/picoclaw mcp add crm \
  "http://127.0.0.1:8085/mcp" -t http -H "Authorization: Bearer $BRIDGE_TOKEN" -f
```

`scripts/install.sh` does this for you.

## Errors

| Status | Meaning |
|---|---|
| 401 | Missing/incorrect credentials, or an expired WhatsApp session (GOWA) |
| 403 | Cross-site form, missing/incorrect CSRF token |
| 404 | Unknown route, post or media name |
| 413 | Body larger than 26 MiB |
| 429 | Too many failed logins from this IP (10 in 5 minutes) |
| 500 | Unexpected error — the log names the failing path |
