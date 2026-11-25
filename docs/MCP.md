# MCP server (EspoCRM + WhatsApp)

The bridge exposes a **Model Context Protocol** server at `POST /mcp`, inside the
same process as the webhook bridge — no extra daemon, no extra memory.

Transport: JSON-RPC 2.0 over HTTP (one POST → one JSON response). `GET /mcp`
returns `405` because no SSE stream is offered.

Auth: the same `BRIDGE_TOKEN` as `/webhook/espocrm`, sent as a bearer token.

```bash
TOKEN=$(grep '^BRIDGE_TOKEN=' ~/gowa-espo/.env | cut -d= -f2-)
```

## Tools

| Tool | Purpose |
|------|---------|
| `crm_search` | search Contact/Lead/Case/Account/WhatsAppChannelPost by text or phone |
| `crm_get` | fetch one record by id |
| `crm_create_channel_post` | create a post; `status: "Ready to Publish"` publishes it immediately |
| `crm_update_channel_post` | update a post (e.g. publish or retry) |
| `crm_list_ready_posts` | queue view of posts waiting to publish |
| `wa_send` | send a WhatsApp text to a phone or a channel JID |
| `wa_channel_messages` | read the latest messages of a channel |
| `bridge_health` | dependencies + outbox queue depth |

## Handshake

```bash
curl -s -X POST http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
```

```json
{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"tools":{"listChanged":false}},
  "serverInfo":{"name":"gowa-espocrm-mcp","version":"1.0.0"},
  "instructions":"EspoCRM + WhatsApp control plane…"}}
```

## List and call tools

```bash
curl -s -X POST http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# find a contact
curl -s -X POST http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"crm_search","arguments":{"entity":"Contact","phone":"+966501234567"}}}'

# create a post that publishes immediately
curl -s -X POST http://127.0.0.1:8085/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
        "name":"crm_create_channel_post","arguments":{
          "name":"إعلان","channelJid":"120363024512399999@newsletter",
          "body":"نص المنشور","status":"Ready to Publish"}}}'
```

Tool results are returned as MCP `content: [{type:"text", text:"<json>"}]`.
Failures set `isError: true` with the upstream error text — never an exception.

## Connecting a client from another machine

The bridge binds `127.0.0.1` on the phone. Reach it through the SSH tunnel you
already use, without exposing anything publicly:

```bash
ssh -N -L 18085:127.0.0.1:8085 smartp      # keep running
```

Then point any MCP client at `http://127.0.0.1:18085/mcp`:

```json
{
  "mcpServers": {
    "espocrm": {
      "type": "http",
      "url": "http://127.0.0.1:18085/mcp",
      "headers": { "Authorization": "Bearer <BRIDGE_TOKEN>" }
    }
  }
}
```

On the phone itself, use `http://127.0.0.1:8085/mcp` directly.

## Safety

- Every tool is scoped by the API user's role: Contact, Lead, Case, Account,
  WhatsAppChannelPost, Note. There is no admin credential in the bridge.
- `wa_send` can message anyone the linked account can message. Treat the token
  like a password; rotate it by editing `.env` and restarting `bridge`.
