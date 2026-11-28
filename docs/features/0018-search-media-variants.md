# 0018 — Search, a media library, and A/B siblings

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.8.0
- **Roadmap:** R-27
- **Files:** `bridge/ui.py`, `bridge/app.py`, `bridge/crm.py`, `bridge/mcp.py`

## Why

Three capabilities existed but were reachable only by the agent:

- `semantic_search` had no page — an owner browsing the archive could not search it.
- Media files had no index: the same photo was uploaded twice, and an unused file could not
  be spotted.
- Testing two versions of a post meant creating both by hand and remembering which was which.

## How

**`/ui/search`** — a form over `semantic_search` (BM25 + Arabic stemming), 20 results with
status, type, views, score and snippet; each links to the post. Reachable from a chip on the
content page.

**`/ui/media`** — every file in `MEDIA_DIR` with size, kind, image thumbnail, and the titles
of posts that use it ("غير مستخدم" when nothing references it). Reachable from the channel
page.

**A/B variants** — `crm_create_variant(post_id)` creates a sibling draft with
`variant_of = parent` (max 3, labelled B/C); both are ordinary posts, so metrics, lint,
scheduling and publishing work unchanged. `crm_variant_results(post_id)` orders the family by
views and names the current winner, with the note that a verdict needs 48 hours.

## Verify

```bash
python3 -m unittest bridge.tests.test_ops.VariantTest
curl -su crm:$BRIDGE_TOKEN 127.0.0.1:8085/ui/search?q=المنتجات   # results page
curl -su crm:$BRIDGE_TOKEN 127.0.0.1:8085/ui/media              # library page
```

## Limits

- Search is lexical (no synonyms); a zero-result page means "no shared words".
- The media library lists files, it does not delete them — deletion stays deliberate.
- Variants are compared by raw views; with small numbers the winner is a hint, not proof.
- Publishing both variants at once would split the audience; the skill keeps them as drafts
  until the owner schedules one.

## Links

- [0012 — topic intelligence](0012-topic-intelligence.md)
- [0015 — media, lint, slot](0015-media-lint-slot.md)
