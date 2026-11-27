# 0014 — The weekly plan as an object, one-tap approval, Sunday digest

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.6.0
- **Roadmap:** R-23
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `bridge/ui.py`, `bridge/app.py`, `bridge/digest.py`, `bridge/service.py`, `picoclaw/skills/content-strategist/SKILL.md`

## Why

Plans lived in the chat: the agent produced a good table, the owner replied "اعتمد", and
nothing happened — no record, no drafts, no link to the posts. Two weeks later nobody could
tell which plan was approved or what came of it. A plan that is not an object cannot be
approved, measured or repeated.

## How

**`crm_plans` + `crm_plan_items`** (one plan per week, enforced by a unique index):

- `crm_save_plan(week_start, items[])` — items carry title, body, kind, goal and a local
  `slot_at`. Re-saving the same week **replaces** the items (that is the edit path); an
  **approved** plan is immutable, so history cannot be rewritten.
- `crm_get_plan` — latest, by id, or by week.
- `crm_approve_plan(plan_id, channelJid?)` — for every item without a post: create a draft,
  schedule it at `slot_at` when present, store `post_id` back on the item. Idempotent
  (second call returns `already: true`).
  **Media items are the exception:** an image/video/audio/file post with no file is kept as a
  draft and never scheduled — the agent's own approval run surfaced this ("these two need
  media or they will fail at publish time"), and scheduling a doomed post is worse than
  leaving a visible draft. `/ui/plan` says «أرفق الوسائط ثم أعد الجدولة» next to it.
- The channel defaults to the stored channel profile, then to the last post's channel, so the
  agent never has to know a JID.

**UI**: `/ui/plan` shows the current week, each item with kind, local slot and a link to its
draft, plus one gold action — «اعتماد الخطة وإنشاء المسودات» (same-origin + CSRF like every
other form). The Today page gains a plan card.

**Agent discipline** (skill): save the plan first, present it from the stored object, create
drafts only on an explicit approval word, and use `crm_approve_plan` rather than creating
posts by hand.

**Weekly digest** (`bridge/digest.py`): deterministic text — posts, views, average, best type,
best slot, upcoming scheduled count, plan state, top opportunity. Sent Sunday 20:00 local by
a daemon thread in the bridge (no cron dependency), at most once per six days, tracked in
`meta.last_digest_at`. Delivery uses the Telegram bot PicoClaw already owns (token read from
`.security.yml`, chat from `config.json`), falling back to `termux-notification`, and always
writes to the bell.

## Verify

```bash
python3 -m unittest discover -s bridge/tests    # 52 tests
# plans: save → replace same week → approve (drafts + scheduled) → idempotent → immutable
# digest: Sunday 20:00 window, six-day guard, wrong day, text contains the numbers,
#         credentials parsed from a temp pico home
curl -s -u crm:$BRIDGE_TOKEN 127.0.0.1:8085/ui/plan
```

## Limits

- One plan per week by design; two parallel drafts of a plan are not supported.
- The digest is deterministic, not narrated: it tells the numbers, not a story. A narrated
  version is an agent task and would cost a model call every week.
- Telegram delivery depends on PicoClaw's bot config; if the token moves, the digest falls
  back to a Termux notification without failing.
- `slot_at` is interpreted in the owner's offset (`APP_TZ_OFFSET`), never UTC.

## Links

- [0012 — topic intelligence](0012-topic-intelligence.md)
- [0008 — notifications](0008-notifications.md)
