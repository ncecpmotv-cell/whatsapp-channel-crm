# 0009 — Push notifications (Telegram + Termux:API)

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.2.0
- **Roadmap:** R-18
- **Files:** `bridge/notify.py`, `bridge/config.py`, `bridge/service.py`, `bridge/app.py`

## Why

The bell in the app records events, but it only helps someone already looking at the app.
The owner's phone spends its day with the screen off, so "the post failed" and "the post was
published" have to reach the lock screen or they reach nobody.

## How

`PushNotifier` is wired into `CrmClient.notify()`, so every event that reaches the bell also
reaches the configured channels:

- **Telegram** — `sendMessage` with the title, body and an absolute link built from
  `PUBLIC_BASE_URL`. Works with the app closed and from any device.
- **Termux:API** — `termux-notification --title … --url …`, a local Android notification.

Design rules:

- **Never on the hot path:** `send()` spawns a daemon thread; a dead network cannot delay or
  roll back a delete.
- **Never raises:** channel errors are logged and swallowed; a push failure is not a business
  failure.
- **Two independent channels**, chosen by configuration, not code: a machine without
  `termux-notification` simply uses Telegram.
- **Event filter** `PUSH_EVENTS` (default `publish,failed`; the owner sets
  `content,publish,failed` so deletes/cancels/schedules also ring).
- **No secrets in diagnostics:** `/health` reports `{"telegram": bool, "termux": bool,
  "events": […], "enabled": bool}` and never the token.

## Verify

```bash
curl -s 127.0.0.1:8085/health | jq .push
# {"telegram":false,"termux":true,"events":["content","failed","publish"],"enabled":true}

# delete a draft through the UI → a notification appears on the phone
```

Unit tests cover: disabled state, event filter, Telegram payload/link, Termux argument
shape, and that a channel exception is swallowed (7 tests in `test_notify.py`).

## Limits

- Termux:API needs both the package and the F-Droid app; without the app the command exists
  and does nothing.
- Android may delay notifications when the system is in deep doze; making Termux
  "Unrestricted" in battery settings reduces that.
- Telegram delivery requires the bot token and a chat the bot may write to; a wrong chat id
  fails silently by design (logged as a warning).

## Links

- [0008 — notifications](0008-notifications.md)
- `docs/SETUP-FROM-ZERO.md` §5
