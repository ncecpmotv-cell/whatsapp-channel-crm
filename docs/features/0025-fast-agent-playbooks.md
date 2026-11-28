# 0025 — Four fast playbooks and the two tools that make them cheap

- **Status:** shipped and installed on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.4.0
- **Roadmap:** R-34
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `bridge/tests/test_pack.py`, `picoclaw/skills/reply-desk/SKILL.md`, `picoclaw/skills/hook-lab/SKILL.md`, `picoclaw/skills/repurpose/SKILL.md`, `picoclaw/skills/publish-runbook/SKILL.md`

## Why

The agent had tools but no **procedure** for three daily jobs (answering the inbox, sharpening a
hook, reusing a winner) and one safety job (pre-flight before publishing). Procedure in the system
prompt is vague and expensive; procedure as a skill plus one context tool costs one model call.

## How

**Two context tools** (40 total):

| tool | replaces | returns |
|---|---|---|
| `crm_inbox(limit, all)` | searching contacts + messages separately | unread DMs with name, phone, org, stage, body ≤400 chars |
| `crm_post_pack(id)` | post + insights + lint + plan + brand + search | body, metrics, lint issues, plan slot, brand version, visual brief, 4 closest archived posts |

**Four skills, each with an explicit call budget:**

- **`reply-desk`** — classify inbound deterministically (سؤال/طلب/شكوى/سبام/فرصة by keywords and
  question marks), draft up to five replies in **one** call, never send without an explicit
  «أرسل», escalate complaints instead of apologising automatically.
- **`hook-lab`** — eight hooks in **one** call, then a local score: `+2` length 35–70, `+1` number,
  `+1` question, `−2` ≥0.6 Jaccard against the archive, `−1` a word from the brand `donts`.
  Returns the top three with the reason, no writes.
- **`repurpose`** — one `crm_post_pack`, then three formats in one call: 3-part text series,
  30-second video script (4 shots), 45-second audio script. No claim that is not in the source.
- **`publish-runbook`** — **zero model calls**: list ready posts, lint each, check 30-minute slot
  collisions, print a pass/block table; after 24h, one line comparing the post with the channel
  average plus a single experiment.

## Verify

```bash
python3 -m unittest discover -s bridge/tests     # 89 tests (3 new: inbox, pack, missing post)
```

On the phone:

```
tools: 40
skills: channel-brand · content-strategist · editorial-board · hook-lab
        publish-runbook · reply-desk · repurpose   (all workspace-readable)
crm_inbox      → {"count": 0, "messages": []}
crm_post_pack  → id 83746911c527 · views 16 · lint [visual_brief_missing] · 3 similar · brand v4
```

## Limits

- `crm_inbox` reads only what GOWA already delivered; it does not fetch history.
- The classifier is lexical: an angry customer who writes politely will be classified as سؤال.
  The skill says so, and the owner still approves every send.
- `post_pack.similar` is BM25 over the archive, not semantics.
- Skills cost one model call each by design; running all four in one turn is four calls, which the
  free-model budget can absorb but the owner should not script in a loop.

## Links

- [0023 — editorial board](0023-editorial-board-and-agent-guard.md)
- [0024 — visual spec](0024-editable-identity-and-visual-spec.md)
