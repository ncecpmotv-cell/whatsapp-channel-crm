# 0024 — Editable identity, and a spec the agent cannot improvise

- **Status:** shipped and verified on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.3.0
- **Roadmap:** R-33
- **Files:** `bridge/ui.py`, `bridge/app.py`, `bridge/crm.py`, `bridge/mcp.py`, `picoclaw/skills/channel-brand/SKILL.md`, `bridge/tests/test_brand.py`, `docs/BRAND-KIT.md`

## Why

The identity existed as data but could only be changed through the agent, and the visual half was
prose: "gold for one action" tells a model nothing about which hex to use on an image. The owner
asked for two things: edit the identity **inside the project**, and make PicoClaw **know** it when
it creates visual content instead of inventing a look.

## How

**`/ui/brand` is now a form.** Name, tagline, tone, four palette pickers, fonts, image/video
formats, do/don't lists, the visual never-list, logo policy, text-on-image limits and the channel
limits (chars, MB, per-day). Server-side validation rejects a non-hex colour or a malformed format
(`_brand_patch` in `app.py`), every save bumps `version` and `updated_at`, and the page shows both
— so a change is traceable and the agent can be told "use version N".

**`crm_visual_brief(kind, topic)`** resolves roles to concrete values — background/text/accent hex,
format, fonts, logo policy, `never`, and five imperative rules. Deterministic, no model call, ~1 KB.

**Media posts must carry it.** `crm_create_channel_post` accepts `visual_brief` and stores it in
`meta`; `crm_lint_post` then reports:

| code | severity | when |
|---|---|---|
| `visual_brief_missing` | warning | image/video/audio post with no `visual_brief` |
| `brand_violation` | warning | the brief mentions an item from `never` (شعار شخصي، مونوغرام…) |
| `off_palette` | warning | the brief names a hex outside the palette |

The scan deliberately skips `never`, `rules` and `palette` — the first version read its own
forbidden list and flagged every correct brief.

**The skill was rewritten around this.** `channel-brand` now orders: call `crm_visual_brief` before
any visual draft, pass the result through unchanged, never invent a logo/letter/signature/colour/
font, and **stop and ask** when the identity is empty (version 0 or empty palette).

## Verify

```bash
python3 -m unittest bridge.tests.test_brand   # 7 tests: version bump, spec resolution,
                                             # missing brief, violation, off-palette, validation
```

Live on the phone:

```
tools: 38
crm_visual_brief → 1080x1350 · background #2A3A31 · text #F5F1E9 · accent #B08A3E · 6 never
POST /ui/brand/save (real CSRF) → brand v3, gold #B08A3E, chars 1200, format 1080x1350
crm_lint_post on an image draft → ['media_missing', 'visual_brief_missing']
```

The test edits were then rolled back to the shipped defaults (v4) and the two probe drafts deleted.

## Limits

- The agent still can't *see* an image it didn't generate: enforcement is on the brief and the
  text, not on pixels. If an image model is added later, `crm_visual_brief` is already its prompt.
- Audio posts inherit the palette rules but only the format and never-list are meaningful.
- `version` is a counter, not a diff log; history lives in git for the docs and in `updated_at` here.
- The UI edits one channel; multiple channels would need a brand per channel.

## Links

- `docs/BRAND-KIT.md`
- [0020 — brand kit](0020-brand-kit.md)
- [0023 — editorial board](0023-editorial-board-and-agent-guard.md)
