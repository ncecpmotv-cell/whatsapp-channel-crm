# 0023 — Editorial board: two phases, one briefing, and a human-only gate

- **Status:** shipped and exercised end-to-end on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.2.0
- **Roadmap:** R-32
- **Files:** `bridge/mcp.py`, `bridge/app.py`, `bridge/config.py`, `bridge/tests/test_guard.py`, `picoclaw/skills/editorial-board/SKILL.md`, `scripts/phone-update.sh`

## Why

The radar finds topics, but nothing turned them into a week of work without burning model calls on
copy that might be rejected. And the agent could approve its own plan: `crm_approve_plan` had no
caller check, so "the human gate" existed only in prose.

## How

**Two phases, and the split is the cost control.**

- *Phase A (proposal, no bodies):* `crm_editorial_brief` → 4–6 themes → `crm_save_plan` with
  `status: proposed`. Titles, kinds, goals and slots only. The critic checks each theme with
  `semantic_search` before saving.
- *Phase B (writing, after the owner approves):* for approved items without a post,
  `crm_create_channel_post` as **draft**, then `crm_lint_post`. Nothing publishes.

`crm_editorial_brief` replaces five calls with one compact payload: channel numbers (posts, views,
avg, engagement, cadence, subscribers and delta), per-type averages, best slots with sample size,
top opportunities, five radar angles, current plan state, and the brand's tone/donts/limits.

**The gate is code, not instructions.** `AGENT_TOKEN` is a second bearer token:

| Token | Can draft | Can read | Can approve/schedule/publish |
|---|---|---|---|
| `BRIDGE_TOKEN` (owner/UI) | yes | yes | yes |
| `AGENT_TOKEN` (PicoClaw) | yes | yes | **no — `isError`** |

`McpServer.handle(request, caller=…)` stores the caller per request (thread-local);
`crm_approve_plan`, `content_schedule` and any `status: scheduled|published` update call
`_human_only()` and return `-32003`. PicoClaw's MCP header now carries the agent token, so the
distinction is real on the device.

**Scheduling.** `picoclaw cron add -n editorial-board -c "0 10 * * 1"` → «Next run 2026-11-30
10:00». The skill file ships in the repo and is copied to both `$PICOCLAW_HOME/skills` and
`$PICOCLAW_HOME/workspace/skills` — PicoClaw's `read_file` is workspace-restricted, so a global
skill the model decides to open by path fails with `path escapes workspace`.

## Verify

```bash
python3 -m unittest bridge.tests.test_guard    # 5 tests: agent refused, human not blocked
```

Live on the phone, with the real agent token:

```
tools: 37
agent  crm_approve_plan   → isError «plan approval is human-only: use the CRM UI»
agent  content_schedule   → isError «scheduling is human-only: use the CRM UI»
human  crm_approve_plan   → normal validation error (not a permission error)
agent  crm_editorial_brief → 43 posts · 5 angles · 3 slots · 4 opportunities
```

One real agent run produced plan `0eeb5710478f` for 2026-12-07: three items, `status: proposed`,
not approved, and it deliberately chose a later week so an approved plan would not be overwritten.

## Limits

- One briefing covers one window; multi-channel brands would need a per-channel brief.
- The agent may still *draft* freely — the gate protects approval and scheduling, not the archive.
- `AGENT_TOKEN` is optional: unset, every caller counts as human (backwards compatible, and the
  gate is inert — set it in production).
- Phase B requires an explicit approval word; the cron never writes bodies.

## Links

- `picoclaw/skills/editorial-board/SKILL.md`
- [0022 — radar and the reporting board](0022-radar-and-reporting-board.md)
