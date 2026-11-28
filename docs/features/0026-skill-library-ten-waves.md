# 0026 — مكتبة المهارات: عشر موجات، ٢٧ مهارة، وأربعة سيرفرات MCP

- **Status:** shipped and installed on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.15.0 (waves v4.5.0 → v4.14.0)
- **Roadmap:** R-35
- **Files:** `bridge/mcp.py`, `scripts/phone-update.sh`, `picoclaw/skills/skill-router/SKILL.md`, `picoclaw/skills/metrics-glossary/SKILL.md`

## Why

The agent had seven playbooks. The owner asked for a library that covers the whole arc — creation,
planning, analysis, interpretation, distribution — free of charge and fast. "Fast" here is a
number: **one model call per skill**, or zero.

## The library (27 skills, ten waves)

| Wave | Tag | Skills |
|---|---|---|
| 1 | v4.5.0 | `insight-interpreter` · `audience-persona` |
| 2 | v4.6.0 | `title-formulas` · `carousel-builder` |
| 3 | v4.7.0 | `distribution-plan` · `crosspost-adapter` |
| 4 | v4.8.0 | `launch-calendar` · `series-planner` |
| 5 | v4.9.0 | `weekly-review` · `retention-audit` |
| 6 | v4.10.0 | `ab-designer` · `offer-builder` |
| 7 | v4.11.0 | `fact-check-lite` · `source-log` |
| 8 | v4.12.0 | `community-prompts` · `collab-pitch` |
| 9 | v4.13.0 | `voice-desk` · `incident-comms` |
| 10 | v4.14.0 | `skill-router` · `metrics-glossary` |

Pre-existing: `content-strategist` · `channel-brand` · `editorial-board` · `reply-desk` ·
`hook-lab` · `repurpose` · `publish-runbook`.

`skill-router` maps every request to **one** skill so 27 playbooks do not fight for the same prompt.
`metrics-glossary` stops the classic misreading: views are opens, not unique readers, and a
three-post average is not a trend.

## MCP: what was added and what was refused

Verified live (`initialize` → 200, no key), added to PicoClaw:

- `cloudflare_docs` — `https://docs.mcp.cloudflare.com/mcp` (the project keeps shipping edge code)
- `deepwiki` — `https://mcp.deepwiki.com/mcp` (repo questions when integrating open source)

Refused on purpose: search/extract MCPs (Tavily, Exa, Brave, Firecrawl) duplicate the built-in
`tools.web` and the edge worker's `edge_web_extract`, and every server costs context on every turn.
The phone runs **four** servers: `crm`, `edge`, `cloudflare_docs`, `deepwiki`.

## How it reaches the phone

`scripts/phone-update.sh` copies `picoclaw/skills/` to `$ROOT/picoclaw`, then mirrors it to
`$PICOCLAW_HOME/skills` **and** `$PICOCLAW_HOME/workspace/skills` (PicoClaw's `read_file` is
workspace-restricted). One command installs all 27; the installer does the same on a fresh device.

## Verify

```
picoclaw skills list        → 27
picoclaw mcp list           → cloudflare_docs · crm · deepwiki · edge   (all enabled)
crm tools                   → 40   (unchanged; skills use existing tools)
```

No new cloud cost: every skill is text plus existing MCP tools; the only remote calls are the ones
the tools already made (edge AI 40/day cap, R2 64MB cap).

## Limits

- Skills are instructions, not enforcement. The hard gates remain in code: `AGENT_TOKEN` blocks
  approval/scheduling, `crm_lint_post` blocks empty and media-less posts, cost caps refuse.
- 27 skills in one directory is close to the point where `skill-router` matters; beyond ~35 the
  descriptions should be grouped by phase.
- Two new MCP servers add tool schemas to every turn. If the model starts ignoring skills, disable
  `deepwiki` first (least used) and re-measure.

## Links

- [0025 — fast playbooks](0025-fast-agent-playbooks.md)
- [0024 — visual spec](0024-editable-identity-and-visual-spec.md)
