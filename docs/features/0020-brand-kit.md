# 0020 — Brand kit: identity as data, limits as rules

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.0.0
- **Roadmap:** R-29
- **Files:** `bridge/crm.py`, `bridge/mcp.py`, `bridge/ui.py`, `bridge/app.py`, `docs/BRAND-KIT.md`, `picoclaw/skills/channel-brand/SKILL.md`

## Why

The agent wrote good Arabic but in whatever voice the prompt implied that day, and the visual
rules lived in the owner's head. Identity that is not stored is identity that drifts. The same
goes for limits: a poll, a 30 MB video or a personal monogram only gets caught after the fact.

## How

**`crm_get_brand` / `crm_set_brand`** — a brand document in `meta.brand`, deep-merged on
update, with defaults that encode the owner's standing rules:

```json
{"palette": {"deep": "#2A3A31", "sage": "#3E4D42", "gold": "#C5A059", "beige": "#F5F1E9"},
 "fonts": {"display": "Tajawal", "body": "IBM Plex Sans Arabic"},
 "tone": "فصحى حديثة، جمل قصيرة…",
 "dos": ["فائدة واحدة…"], "donts": ["بلا شعارات أو أسماء شخصية", "بلا استبيانات…"],
 "limits": {"max_chars": 1024, "media_mb": 20, "per_day": 30, "polls": false}}
```

**`/ui/brand`** renders it: colour swatches, fonts, tone, the two lists, and the limits as
stats. Reachable from the channel page.

**Skill `channel-brand`** loads before any copywriting: read the brand, refuse the prohibited
things even if asked, search the archive before repeating an idea, and update through
`crm_set_brand` rather than editing files.

The limits are not decorative: `crm_lint_post` warns past 1,024 chars, `crm_attach_media`
enforces 20 MB, the outbox enforces the daily cap, and channels reject polls before send.

## Verify

```bash
python3 -m unittest bridge.tests.test_edge.BrandTest
# defaults include «بلا شعارات أو أسماء شخصية» and polls=false
# partial update deep-merges: gold changes, deep stays
curl -su crm:$BRIDGE_TOKEN 127.0.0.1:8085/ui/brand    # swatches + limits
PICOCLAW_HOME=~/pico ~/pico/bin/picoclaw skills list   # channel-brand
```

## Limits

- One brand per install; multi-channel branding would need a per-channel row.
- The UI page is read-only: changes go through the agent or `crm_set_brand`.
- Palette/fonts are guidance for humans and copy; the server-rendered UI keeps its own design
  tokens, so a brand change does not repaint the app (that would be a separate theme pass).

## Links

- `docs/BRAND-KIT.md`
- [0012 — topic intelligence](0012-topic-intelligence.md)
