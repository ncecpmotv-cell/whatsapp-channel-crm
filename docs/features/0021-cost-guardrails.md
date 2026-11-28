# 0021 — Cost guardrails: refuse instead of billing

- **Status:** shipped and enforced on the live Worker
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.0.2
- **Roadmap:** R-30
- **Files:** `edge/src/ops.js`, `edge/src/index.js`, `edge/wrangler.toml`, `edge/test/ops.test.js`, `bridge/edge.py`, `bridge/ui.py`, `bridge/app.py`, `docs/COST-GUARDRAILS.md`

## Why

The owner enabled R2 and said, in effect: *the project must not use the paid tier — save this as a
rule for every future feature.* R2 bills $0.015/GB-month, $4.50 per million Class A operations
and $0.36 per million Class B once the free tier (10GB, 1M, 10M) is passed, and Workers AI bills
neurons after 10,000/day. A feature that merely "behaves" is one runaway loop away from an invoice.

## How

**Hard budgets, enforced at the edge** (`BUDGET` in `ops.js`, overridable from `wrangler.toml`):

| Variable | Value | Effect |
|---|---|---|
| `KEEP_BACKUPS` | 3 | newest three archives only; older deleted on upload |
| `MAX_BACKUP_MB` | 8 | one archive: `413` |
| `MAX_TOTAL_MB` | 64 | total storage: `507` before writing |
| `AI_DAILY_LIMIT` | 40 | AI calls per UTC day: `429`, counter in KV with 48h TTL |

**Retention is decided by R2's own listing, not the KV index.** KV is eventually consistent; the
first implementation pruned from a stale read and deleted the three *newest* archives while keeping
the two oldest. `listObjects()` now lists the bucket (1 Class A), sorts by `uploaded`, keeps the
newest N and rewrites the KV index afterwards — KV is a cache for the status page, never the truth.

**`GET /usage`** returns the live picture — backup count/keep, used MB/budget, AI used/limit, and
the free-tier line — and `/ui/edge` renders it in Arabic («نسخ محفوظة 3/3 · مساحة 0.05/64 MB ·
استدعاءات الذكاء 1/40»). `GET /backup` also lists live, and `POST /backup/prune` re-applies
retention by hand.

## Verify

```bash
cd edge && npm test        # 25 tests, incl. "retention keeps the newest three" and "a full
                           # storage budget refuses the upload instead of billing" (507)
curl -s $EDGE/usage -H "Authorization: Bearer $TOKEN"
# {"backups":{"count":3,"keep":3,"usedMB":0.05,"budgetMB":64},"ai":{"used":1,"limit":40},…}
```

Measured live: a 9MB upload answered `413 {"error":"archive exceeds 8MB budget","limit":true}`;
four sequential 5KB archives left exactly three objects in R2; total usage 0.05MB of a 64MB cap.

## Limits

- The AI counter is per UTC day in KV, so two concurrent calls can both pass at the boundary
  (a one-call overshoot at worst, still ~1% of the daily cap).
- `MAX_TOTAL_MB` counts encrypted sizes, not the bucket's billing rounding.
- These are project budgets, not Cloudflare spend limits: the account-level spend cap is a
  separate dashboard setting and should stay at zero for this account.

## Links

- `docs/COST-GUARDRAILS.md` (the rule, the prices, the arithmetic, the rules for future features)
- [0019 — off-site backups](0019-edge-backups-status-ai.md)
