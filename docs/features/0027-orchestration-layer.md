# 0027 — طبقة التنسيق: فكرة واحدة تُشغّل كل الأنظمة

- **Status:** shipped and verified on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.16.0
- **Roadmap:** R-36
- **Files:** `bridge/orchestrator.py`, `bridge/mcp.py`, `bridge/ui.py`, `bridge/app.py`, `bridge/crm.py`, `bridge/tests/test_orchestrator.py`, `picoclaw/skills/orchestrator/SKILL.md`, `picoclaw/skills/strategic-plan/SKILL.md`, `picoclaw/skills/strategic-analysis/SKILL.md`, `picoclaw/skills/visibility-plan/SKILL.md`, `docs/MODELS.md`

## Why

Two problems at once. First: the owner gives one sentence («عندي فكرة…») and the agent spends
turns collecting context before deciding. Second: 27 skills with no entry point — each one correct,
none knowing which comes first. And when the model becomes free-tier (Ollama Cloud, OpenRouter
free), every wasted turn is a wasted quota.

## How

**`crm_orchestrate(idea, mode?)`** — deterministic, no model call. It classifies the intent
(`plan · write · analyze · visibility · launch · distribute · reply`) by keyword, then returns one
payload: compact numbers, three angles, plan state, the **skill order**, the **exact next tool
calls**, the guards and a call budget. The model's job becomes execution, not collection.

**`crm_capabilities()`** — what exists right now: skills installed, MCP servers, cron jobs, guards,
cost caps and the last runs. Rendered at **`/ui/capabilities`**.

**Every run is recorded** (`crm_runs`): mode, idea, step count — so the board can show what the
agent actually did, not what it said.

**Four strategy skills**, each one `orchestrate` call + one model call:

| skill | answers |
|---|---|
| `strategic-plan` | positioning, 3 pillars, 90-day arc with one metric per phase |
| `strategic-analysis` | portfolio: double-down / stop / experiment, decided by numbers |
| `visibility-plan` | three discovery channels ranked by cost, one action each |
| `orchestrator` | the entry rule: call it first, follow `steps`, never re-read the brief |

`skill-router` and `editorial-board` now start from `crm_orchestrate`, so old skills are not
orphaned: they became the second step of a routed flow.

**Freed MCP servers.** Added `context7` (verified 200, no key) next to `cloudflare_docs` and
`deepwiki`; five total with `crm` and `edge`. Refused: Tavily/Exa/Brave/Firecrawl (they duplicate
`tools.web` + edge, and every server's schemas ride in the prompt each turn).

**Scheduling.** A daily `orchestrator` cron at 07:30 asks for a five-line morning brief; the weekly
`editorial-board` cron at Monday 10:00 stays. Both are agent turns, neither may draft or publish.

## Verify

```bash
python3 -m unittest bridge.tests.test_orchestrator   # 4 tests: routing, pack shape, run log, matrix
```

On the phone:

```
tools: 42  (crm_orchestrate + crm_capabilities added)
crm_orchestrate "أبي خطة أسبوع لسلسلة منتجات"
  → mode plan · skills [editorial-board, strategic-plan] · 2 steps · 2 model calls
crm_capabilities → skills 31 · mcp 5 · cron 2
/ui/capabilities → 6.5 KB, sections: القدرات · المهارات · سيرفرات MCP · المهام المجدولة ·
                    بوابات المنع · آخر تشغيلات · سقوف التكلفة
```

## Limits

- Routing is lexical: an idea phrased without any keyword falls to `plan`. Pass `mode` explicitly
  when it matters.
- The pack is advice plus a checklist; the model can still ignore it. The hard gates (approval,
  lint, cost caps) remain in code.
- `crm_capabilities` reads the agent home from disk; on a host without PicoClaw it returns zeros —
  honest, not decorative.
- Five MCP servers is the practical ceiling for a free-tier context budget; adding a sixth should
  remove one.

## Links

- `docs/MODELS.md` — free-tier models and the seven token rules
- [0026 — skill library](0026-skill-library-ten-waves.md)
