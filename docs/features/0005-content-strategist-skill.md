# 0005 — Content Strategist skill for PicoClaw

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.1.0
- **Roadmap:** R-05
- **Files:** `picoclaw/skills/content-strategist/SKILL.md`, `scripts/install.sh`

## Why

The agent had the right tools (`content_insights`, `posting_times`) but no method: the same
prompt produced a data-backed plan one day and generic advice the next. Owners cannot audit
advice they cannot reproduce, so the loop has to be written down and installed, not
remembered in a chat.

## How

A PicoClaw skill — a markdown procedure the agent loads when the request matches
(content plan, analysis, "what should we publish"):

1. Read the numbers first (`content_insights` 30 d, `posting_times` 90 d, `channel_metrics`),
   and say so when the sample is too small (`posts: 0`, `buckets < 5`).
2. Three-sentence diagnosis: what worked, what failed, which gap exists — each with a number.
3. A 4–7 row plan table: goal, type, idea, slot, and *why that slot* (average views of the
   bucket). Polls are refused because channels do not support them.
4. Create drafts **only on explicit request**, then confirm they are `draft` and that
   publishing stays human.
5. Self-review checklist before delivering; hard prohibitions (never publish, never invent
   metrics, never ship a plan without a success measure).

The installer copies `picoclaw/skills/` into `$PICOCLAW_HOME/skills/` on install and
upgrade, so the skill ships with the product rather than living in someone's home directory.

Decision worth noting: the skill is a **document**, not code. Changing the method does not
require a deploy or a restart of the CRM — only a restart of the gateway, and the diff is
reviewable by a non-programmer.

## Verify

```bash
mkdir -p /tmp/skilltest && cp -R picoclaw/skills/. /tmp/skilltest/skills/
PICOCLAW_HOME=/tmp/skilltest picoclaw skills list
# ✓ content-strategist (global) — يبني خطة محتوى أسبوعية مبنية على أرقام القناة …
```

On a real install: `skills list` shows the skill after `install.sh`, and a prompt such as
«حلّل الأداء ثم اقترح خطة الأسبوع» starts by calling the two analysis tools.

## Limits

- PicoClaw has no local-path `skills install`; the installer copies files. Upgrading PicoClaw
  does not remove them, but a `config reset` does not restore them either — re-run the
  installer if the directory is wiped.
- The skill shapes the agent's method, not its model. A weak model will still produce weak
  prose; it will just be structured and honest about the sample size.
- Arabic-first: prompts in English still work, but the plan format will be Arabic.

## Links

- `docs/PICOCLAW.md`
- `docs/CONTENT-PLAYBOOK.md`
- CHANGELOG: "Content Strategist skill…"
