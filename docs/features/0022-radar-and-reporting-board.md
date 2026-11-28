# 0022 — Trend radar, and a board that reports every feature

- **Status:** shipped, live (edge v0.3.0 + phone)
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.1.0
- **Roadmap:** R-31
- **Files:** `edge/src/radar.js`, `edge/src/index.js`, `edge/test/radar.test.js`, `edge/wrangler.toml`, `bridge/radar.py`, `bridge/crm.py`, `bridge/mcp.py`, `bridge/app.py`, `bridge/ui.py`, `bridge/service.py`, `bridge/tests/test_radar.py`

## Why

Two asks in one: **find topics before competitors do**, and **stop hiding the numbers** — the owner
said plainly that most features produce reports and statistics, and those must show up on the CRM
board instead of living inside separate pages or an agent conversation.

A radar also has to respect the cost rule: no paid tier, no runaway AI spend.

## How

**Edge half (free, cron-driven).** `radar.js` fetches up to 10 RSS/Atom feeds (defaults: BBC
Arabic, Al Jazeera, AITNews) every 30 minutes, parses them without an XML library, hashes each URL
into a rolling 500-entry seen-set in KV, and stores one batch of ≤40 items. **No model call on the
cron path** — a 30-minute schedule would otherwise eat the whole 40-call AI budget before anyone
looked. A dead feed is reported in `failures`, never fatal.

**Phone half (judgement).** `radar.py` scores each headline against the archive with the existing
tokenizer: `score = 0.7 × novelty + 0.3 × recency`, where novelty is `1 − max(Jaccard)` against the
last 150 posts. The edge cannot know what you already said; the phone can. Only items not already
stored (unique URL) are kept, and `summarize=true` spends exactly **one** model call for the top 5
to propose Arabic angles.

**Tools (36 total).** `crm_radar_scan`, `crm_angles`, `crm_angle_use` (creates a **draft** with
the source appended — never publishes), `crm_angle_dismiss`. A background thread scans every two
hours with `summarize=false`, so headlines stay warm at zero AI cost.

**The board.** `/ui` is now «لوحة القيادة» and reports every feature that produces numbers:
average views, engagement rate, cadence per week, subscriber delta (30d), best posting times with
their sample size, content gaps (opportunity themes), radar angles with a count badge, failures,
drafts, last backup and last heartbeat. `/ui/radar` holds the full angle list with «مسودة ·
المصدر · تجاهل».

## Verify

```bash
cd edge && npm test                 # 31 tests (6 radar: parse, CDM/Atom, dedupe, dead feed, 400)
python3 -m unittest discover -s bridge/tests   # 74 tests (novelty, dedupe, one-call summary)
```

Live, on the phone:

```
tools: 36   (radar + angles added)
crm_radar_scan → scanned 40, stored 12, summarized true
top angle score 0.988 · «تايدال تحظر الموسيقى المولّدة بالكامل بالذكاء الاصطناعي…»
angle → draft f5ee2a468903 (status draft, body carries «المصدر:»), angle status → used
/ui → 200, sections: لوحة القيادة · مؤشرات الأداء · أفضل أوقات النشر · فجوات المحتوى ·
        زوايا الرادار · الجودة والتشغيل
/ui/radar → 200, 16 KB
```

## Limits

- Novelty is **lexical** (shared words), not semantic: a rephrased duplicate can pass. The archive
  search tool remains the second check before writing.
- Feeds are configurable only through `RADAR_FEEDS` (JSON array) on the Worker; defaults are
  general-Arabic + tech, not a niche choice.
- One AI call per manual scan, capped by `AI_DAILY_LIMIT=40`; the background scan never calls AI.
- Cron cost: 48 ingest runs/day × 3 feeds ≈ 144 subrequests and ~96 KV writes — inside KV's 1,000
  writes/day, and Workers' 100k requests/day.
- Angles are capped at 12 per scan and never publish themselves; the human gate is unchanged.

## Links

- [0021 — cost guardrails](0021-cost-guardrails.md)
- [0019 — edge backups, status, AI](0019-edge-backups-status-ai.md)
- `docs/COST-GUARDRAILS.md`
