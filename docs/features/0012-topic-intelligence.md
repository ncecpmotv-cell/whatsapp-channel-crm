# 0012 — Topic intelligence: `content_gaps` + `semantic_search`

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.4.0
- **Roadmap:** R-21
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `scripts/phone-update.sh`

## Why

`content_insights` answers "what happened" and `posting_times` answers "when". Neither answers
the two questions a content plan actually starts from: **which themes are under-used**, and
**have we already said this?** Without them the agent invents a new angle for every slot — the
most common way a channel becomes repetitive while feeling busy.

Both answers are cheap: a 22-post archive is a few kilobytes of text. There is no reason to
send it to an embedding API, and no reason to make the phone compute vector maths.

## How

**`content_gaps(days)`** — lexical and explainable, no model:

- tokens are Arabic-normalised (hamza forms, `ى→ي`, `ة→ه`, diacritics stripped) and filtered
  by a stoplist; **bigrams** are the unit of a "theme" (`حملة شتاء`, not `شتاء`).
- a theme needs **≥2 posts** to count: a term seen once is that post's vocabulary, not a
  signal. (First implementation ranked single-post terms and the live archive returned
  `الله،`, `باذن`, `علي` — noise dressed as insight. The rule changed, not the wording.)
- `opportunities` = repeated themes whose average views beat the channel average by 25 %;
  `saturated` = single terms in ≥25 % of posts that sit at or below average.
- plus cadence per week, longest gap, days since the last post, and per-type averages with
  `media_type: none` reported as `text`.

**`semantic_search(query, limit)`** — BM25 over titles (weighted twice) and bodies:

- k1 = 1.5, b = 0.75, IDF over the archive; returns id, title, status, views, score and a
  140-char snippet.
- measured on the real archive: **0.9–1.2 ms** per query, no network, no dependency.

MCP instructions now say: call `content_gaps` with the other two analytics tools before
proposing a plan, and search the archive before inventing a new angle.

## Verify

```bash
python3 -m unittest discover -s bridge/tests     # 42 tests, gaps + search included
# on the production archive (22 posts in the window):
content_gaps(90)  -> opportunities: حملة شتاء (4 posts, 9.0 avg vs 7.1 channel)
semantic_search("المنتجات") -> "أربع قواعد لصورة منتج تبيع" (2.71)
```

The tests assert the two rules that keep the output honest: every opportunity has ≥2 posts
and beats the channel average; `نصائح` (three weak posts) lands in `saturated`.

## Limits

- Lexical only: synonyms are not matched (`إضاءة` vs `ضوء`), so a zero-result search means
  "no shared words", not "no such post". True embeddings are a cloud step
  (`docs/CLOUD-PLACEMENT.md`), not a phone one.
- Bigram themes fragment: three spellings of one idea become three themes.
- Below ~20 posts the ranking is an indicator; the tool says so in `note`.
- `phone-update.sh` copies code and skills from the public repo; it never touches `var/`,
  media or env files, so it is safe to re-run.

## Links

- [0002 — MCP analysis tools](0002-mcp-analysis-tools.md)
- `docs/CLOUD-PLACEMENT.md` (embeddings vs local BM25)
