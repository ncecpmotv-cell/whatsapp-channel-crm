# 0017 — Growth history, a morning brief, and a plan that arrives before you ask

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.8.0
- **Roadmap:** R-26
- **Files:** `bridge/crm.py`, `bridge/digest.py`, `bridge/ui.py`, `bridge/app.py`, PicoClaw cron

## Why

The channel was measured by views only: subscribers existed as a single number overwritten on
every sync, so growth was invisible. The owner also had to remember to look: nothing arrived
in the morning, and nothing proposed next week's plan until asked.

## How

**`crm_channel_daily`** — one row per local day: subscribers, posts, views. Written by
`snapshot_channel_day()`, upserted so re-running is harmless. `channel_growth(days)` returns
the series plus `subscribers_now` and `subscribers_delta`; the channel page shows
«+N مشترك خلال 14 يومًا». A single point says so in `note` instead of drawing a fake trend.

**Daily brief** — 09:00 local, deterministic text: what publishes today with times, drafts
waiting for media, failures in the last 24 h, plan state. Delivered through the same Telegram
bot as the weekly digest, recorded in the bell, once per 20 h.

**Proactive weekly plan** — a PicoClaw cron job (`weekly-plan`, `0 10 * * 4`, Telegram):

> حلّل الأرقام (`content_gaps`, `content_insights`, `posting_times`) ثم اقترح خطة الأسبوع
> القادم بـ3-5 عناصر واحفظها بـ`crm_save_plan`… لا تنشئ مسودات ولا تنشر.

The agent does the analysis and saves a **proposed** plan; approval stays human. Next run
is visible in `picoclaw cron list`.

## Verify

```bash
python3 -m unittest bridge.tests.test_ops.GrowthTest   # idempotent snapshot, delta
python3 -m unittest bridge.tests.test_ops.DailyBriefTest
picoclaw cron list        # weekly-plan · 0 10 * * 4 · next run Thursday 10:00
```

On the device: `snapshot_channel_day()` created a row, `channel_growth(90)` returned
`points` and a delta, and the brief text listed the two blocked drafts.

## Limits

- Growth history starts the day it ships: no retroactive curve.
- The brief is deterministic (no model) — it states facts, it does not interpret them.
- The proactive plan costs one model call per week; if the model provider is down, the job
  fails silently in PicoClaw's log (visible via `cron list` / gateway logs).

## Links

- [0014 — plans and digest](0014-weekly-plan-and-digest.md)
- [0016 — backups and watchdog](0016-backups-and-watchdog.md)
