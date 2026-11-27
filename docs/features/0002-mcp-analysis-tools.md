# 0002 — Analysis tools for the agent (`content_insights`, `posting_times`)

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.1.0 (unreleased at the time of writing)
- **Roadmap:** R-03
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `bridge/tests/test_crm.py`

## Why

An agent asked to "plan next week" without data answers with generic advice. The CRM had
totals (`channel_metrics`) but no aggregation by content type, no cadence, and no view of
which hours actually collect views — so any plan was opinion, not analysis.

## How

Two read-only aggregates over published posts in a window:

- `content_insights(days)` — totals, average views and engagement rate **per media type**,
  posts per week, the top 5 and the weakest 3 posts. Sorted in SQL, aggregated in Python
  (the row count is small by construction: ≤ a few hundred).
- `posting_times(days, tz_offset)` — buckets published posts by `(weekday, hour)` in local
  time and ranks by average views, returning the best eight and the weakest three.

Both are exposed as MCP tools (15 and 16) and the server instructions now tell the agent to
call them **before** proposing a plan. No schema change, no write path, no new dependency.

Decision worth noting: the weekday/hour bucketing is done in Python from `published_at`,
not in SQL, because SQLite's date functions are UTC-only and the owner thinks in Riyadh
time. The timezone comes from `TZ_OFFSET`, overridable per call.

## Verify

```bash
python3 -m unittest discover -s bridge/tests -v     # test_content_insights
```

```text
tools/list → 16 tools, content_insights + posting_times present
content_insights(days=30) → {"posts": 40, "total": {"views": 157, …},
                             "by_type": {"video": {"avg_views": 16.0}, "none": {"avg_views": 3.3}, …}}
```

## Limits

- Only published posts with `published_at`; drafts and cancelled items are ignored.
- Fewer than ~20 published posts makes the ranking noisy — the tool says how many buckets
  it used, and the playbook says to treat it as a hint until then.
- No demographic data: WhatsApp Channels expose views/forwards/reactions only.

## Links

- `docs/API-MCP.md#mcp-server`
- `docs/CONTENT-PLAYBOOK.md`
- CHANGELOG: "Analysis tools for the agent…"
