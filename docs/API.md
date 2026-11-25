# API reference

All examples assume the phone itself (`127.0.0.1`).

## Bridge (:8085)

### `GET /health`

```bash
curl -s http://127.0.0.1:8085/health | python3 -m json.tool
```

```json
{
  "ok": true,
  "gowa": true,
  "espocrm": true,
  "queue": 0,
  "stats": {"inbound": 4, "channel_posts": 1, "dms": 1, "published": 0, "errors": 0},
  "monitoredChannels": ["120363024512399999@newsletter"]
}
```

### `POST /webhook/gowa`

Called by GOWA. Requires a valid `X-Hub-Signature-256` HMAC over the raw body.

```bash
SECRET=$(grep '^GOWA_WEBHOOK_SECRET=' ~/gowa-espo/.env | cut -d= -f2-)
BODY='{"event":"message","payload":{"id":"ABC","chat_id":"966501234567@s.whatsapp.net","from":"966501234567@s.whatsapp.net","body":"مرحبا","is_from_me":false}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -r | cut -d' ' -f1)"
curl -s -X POST http://127.0.0.1:8085/webhook/gowa \
  -H 'Content-Type: application/json' -H "X-Hub-Signature-256: $SIG" -d "$BODY"
```

### `POST /admin/sync`

Force a channel backfill + counter refresh now (normally runs on the
`BRIDGE_CHANNEL_SYNC_INTERVAL` tick). Bearer-token authenticated.

```bash
TOKEN=$(grep '^BRIDGE_TOKEN=' ~/gowa-espo/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8085/admin/sync -H "Authorization: Bearer $TOKEN"
# {"ok": true, "newPosts": 0, "updatedCounters": 3}
```

### `POST /webhook/espocrm`

Called by the EspoCRM hook or by hand. Requires `X-Bridge-Token`
(or `Authorization: Bearer <token>`).

```bash
TOKEN=$(grep '^BRIDGE_TOKEN=' ~/gowa-espo/.env | cut -d= -f2-)

# publish a channel post that is in "Ready to Publish"
curl -s -X POST http://127.0.0.1:8085/webhook/espocrm \
  -H 'Content-Type: application/json' -H "X-Bridge-Token: $TOKEN" \
  -d '{"entityType":"WhatsAppChannelPost","entityId":"<recordId>"}'

# send a free-text WhatsApp message to a Contact
curl -s -X POST http://127.0.0.1:8085/webhook/espocrm \
  -H 'Content-Type: application/json' -H "X-Bridge-Token: $TOKEN" \
  -d '{"entityType":"Contact","entityId":"<contactId>","message":"تم استلام طلبكم"}'
```

## GOWA (:3000)

| Call | Endpoint |
|------|----------|
| Create device slot | `POST /devices` `{"device_id":"primary","webhook_url":"http://127.0.0.1:8085/webhook/gowa"}` |
| Get QR | `GET /devices/primary/login` → `results.qr_link` |
| Connection state | `GET /devices/primary/status` |
| Send text | `POST /send/message` `{"phone":"<jid or +phone>","message":"..."}` |
| Send image | `POST /send/image` (multipart, `phone` + `image`) |
| Follow channel | `POST /newsletter/follow` `{"newsletter_id":"…@newsletter"}` |
| Channel info | `GET /newsletter/info?newsletter_id=…` |
| Latest posts | `GET /newsletter/messages?newsletter_id=…&count=20` |
| Counters | `GET /newsletter/message-updates?newsletter_id=…&after=<serverId>` |
| Subscribe counters | `POST /newsletter/live-updates` `{"newsletter_id":"…@newsletter"}` |
| Download channel media | `GET /newsletter/messages/{server_id}/download?newsletter_id=…` |

All GOWA calls need `X-Device-Id: primary` when more than one device exists.

## EspoCRM (:8081)

```bash
KEY=$(grep '^ESPO_API_KEY=' ~/gowa-espo/.env | cut -d= -f2-)

# list channel posts waiting to publish
curl -s -H "X-Api-Key: $KEY" \
  'http://127.0.0.1:8081/api/v1/WhatsAppChannelPost?maxSize=10&where[0][type]=equals&where[0][field]=status&where[0][value]=Ready%20to%20Publish'

# create a channel post to be published
curl -s -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8081/api/v1/WhatsAppChannelPost \
  -d '{"name":"إعلان","channelJid":"120363024512399999@newsletter","body":"نص المنشور","status":"Ready to Publish"}'

# find a contact by phone
curl -s -H "X-Api-Key: $KEY" \
  'http://127.0.0.1:8081/api/v1/Contact?maxSize=1&where[0][type]=equals&where[0][field]=phoneNumber&where[0][value]=%2B966501234567'
```

### Lifecycle of `WhatsAppChannelPost`

```
New ──(user)──▶ Ready to Publish ──(bridge)──▶ Published
                        │
                        └──(5 failed attempts)──▶ Failed (+ lastError)
```
