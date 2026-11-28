# 0015 — Media from Telegram, a pre-publish lint, and a slot that is not a guess

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.7.0
- **Roadmap:** R-24
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `bridge/config.py`, `bridge/service.py`, `picoclaw/skills/content-strategist/SKILL.md`

## Why

Three gaps showed up in the same week, all in the last metre before publishing:

1. Approving a plan created two media posts with no file — they would have failed at publish
   time. The owner's phone is where the photos already are; the bot should accept them.
2. Nothing checked a post before scheduling: empty text, a duplicate of something said in
   October, two posts in the same half hour.
3. "When should this go out?" was answered by taste, while `posting_times` sat there with
   the answer.

## How

**`crm_attach_media(post_id, path, kind?, at?)`**

- PicoClaw downloads a Telegram photo/video to its workspace; the agent passes that path.
- Paths are restricted to `ATTACH_ROOTS` (default `~`) — a tool that copies any path the model
  names is an exfiltration tool, not a feature.
- Kind is validated against the post's type or inferred from the extension; 20 MB cap;
  a fresh UUID filename in `MEDIA_DIR` (the original name never reaches the filesystem).
- Images get `width`/`height` read from the header (PNG/GIF/JPEG) so the UI keeps CLS at zero.
- If the post came from a plan item with a `slot_at`, it is scheduled there immediately —
  that is the whole point: send the photo, the draft becomes ready and queued.

**`crm_lint_post(post_id)`** returns `{ok, issues[]}` with severity:

| code | severity | rule |
|---|---|---|
| `empty` | error | no title and no body |
| `media_missing` | error | image/video/audio/file post with no file |
| `too_long` | warning | body > 1,024 chars |
| `duplicate` | warning | Jaccard ≥ 0.75 with another post (lexical, explainable) |
| `slot_collision` | warning | another scheduled post within 30 minutes |

`ok` is false only for errors; warnings inform. The skill forbids scheduling when `ok=false`.

**`crm_best_slot(kind)`** — buckets published posts by local weekday/hour, filters by type
when asked, ranks by average views, then returns the next future occurrence that is at least
two hours away and not within an hour of an existing scheduled post. Returns `local` and
`slot_at` so the agent never does date arithmetic.

## Verify

```bash
python3 -m unittest discover -s bridge/tests     # 55 tests
# attach: real PNG header → media_path set, width/height stored, lint flips to ok
# lint: media_missing on a media post; /etc/passwd refused by the root guard
# best_slot: returns a future epoch after a published post exists
```

On the device: attaching a file to one of the two waiting drafts and scheduling it, then
`lint_post` returning `ok: true`.

## Limits

- Duplicate detection is lexical: a paraphrase with different words passes. Real embeddings
  are a cloud step (`docs/CLOUD-PLACEMENT.md`), not a phone one.
- The lint knows nothing about WhatsApp's rendering limits beyond a character warning.
- `crm_attach_media` trusts the caller's path within `ATTACH_ROOTS`; it validates type and
  size, not content (no virus scanning on a phone).
- The Telegram path itself is proven by PicoClaw's own media download; a real photo message
  from the owner is the end-to-end test, not this record.

## Links

- [0014 — plans and approval](0014-weekly-plan-and-digest.md)
- [0012 — topic intelligence](0012-topic-intelligence.md)
