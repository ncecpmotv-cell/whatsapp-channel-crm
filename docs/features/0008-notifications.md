# 0008 — Notifications that actually ring

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.1.0
- **Roadmap:** R-17
- **Files:** `bridge/crm.py`, `bridge/ui.py`, `bridge/app.py`

## Why

The bell existed — table, page, unread counter, "mark all as read" — but only one producer
wrote to it (follow-up reminders). Deleting a post therefore worked and told the user nothing,
which is indistinguishable from "the delete did not happen". On a phone the user is not
watching the list; the bell is the only confirmation that survives leaving the page.

## How

`CrmClient.notify()` is now called by the lifecycle methods themselves, not by the HTTP
handlers, so the same events fire for UI, MCP agents and scheduled work:

| Event | Title | Link |
|---|---|---|
| scheduled (approved) | تمت الجدولة | post |
| published | تم النشر | post |
| publish failed | فشل النشر + reason | post |
| cancelled | أُلغي عنصر | post |
| restored | أُعيد كمسودة | post |
| deleted | حُذف عنصر | content list |

Details that matter:

- **Dedupe keys** on publish/fail (`published:<id>`, `failed:<id>:<error>`) so retries of the
  outbox do not stack identical rows; scheduling is keyed by `(post, at)` so re-scheduling to
  a new time still informs.
- Notifications are written **inside** the same flow as the state change: a delete that
  succeeded always leaves a row, and a failed delete leaves none.
- The bell badge is `unread_notifications()` rendered on every page; the page shows an unread
  dot, the body, the time and a link.
- Draft creation is deliberately silent — the author just made it, and the list already shows
  it. Noise is how a notification centre dies.

## Verify

```bash
# on the device, through the UI exactly like the browser
create draft -> 303
delete       -> 303 ?ok=deleted
curl /ui | grep bell        # class="bell hot" … 🔔1
curl /ui/notifications      # حُذف عنصر · NOTIF-PROBE
# unread: 0 -> 1
```

Unit tests cover the six events, the unread counter and the read-all transition
(`test_lifecycle_notifications`, `test_publish_notifications_dedupe`).

## Limits

- Notifications are stored, not pushed: Android may not wake the browser. The bell is truthful
  when opened; it is not a system push notification.
- The list keeps the last 60 rows; older rows stay in SQLite but are not paginated yet.
- A deleted post's notification links to the content list because the post page is gone.

## Links

- [0001 — content pipeline](0001-content-pipeline.md)
- CHANGELOG 3.1.0
