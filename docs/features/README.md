# Feature records

One page per feature, numbered, never reused. A page answers four questions: why it exists,
how it works, how it was verified, and what it refuses to do. The template is
[`0000-template.md`](0000-template.md).

| # | Feature | Status | Roadmap |
|---|---|---|---|
| [0001](0001-content-pipeline.md) | Content pipeline with human approval | shipped | R-01 |
| [0002](0002-mcp-analysis-tools.md) | `content_insights` + `posting_times` MCP tools | shipped | R-03 |
| [0003](0003-media-and-security.md) | Authenticated media, upload limits, previews | shipped | R-02 |
| [0004](0004-one-shot-installer.md) | One-command installer (GOWA + PicoClaw + CRM) | shipped | R-04 |
| [0005](0005-content-strategist-skill.md) | Content Strategist skill for PicoClaw | shipped | R-05 |
| [0006](0006-phone-start-script.md) | Phone start script (idempotent, ordered) | shipped | R-15 |
| [0007](0007-stack-on-the-phone.md) | The stack moved to the phone | shipped | R-16 |
| [0008](0008-notifications.md) | Notifications that actually ring | shipped | R-17 |
| [0009](0009-push-notifications.md) | Push notifications (Telegram + Termux:API) | shipped | R-18 |
| [0010](0010-installer-tailscale.md) | The installer owns Tailscale | shipped | R-19 |
| [0011](0011-doctor-script.md) | `doctor.sh`: one command that tells the truth | shipped | R-20 |
| [0012](0012-topic-intelligence.md) | Topic gaps + BM25 search over the archive | shipped | R-21 |
| [0013](0013-edge-mcp.md) | edge-mcp: cloud tools that keep the phone light | shipped* | R-22 |
| [0014](0014-weekly-plan-and-digest.md) | Weekly plan object, one-tap approval, Sunday digest | shipped | R-23 |
| [0015](0015-media-lint-slot.md) | Media from Telegram, pre-publish lint, best slot | shipped | R-24 |
| [0016](0016-backups-and-watchdog.md) | Verified backups, watchdog alerts | shipped | R-25 |
| [0017](0017-growth-brief-proactive.md) | Growth history, daily brief, proactive plan | shipped | R-26 |
| [0018](0018-search-media-variants.md) | Search page, media library, A/B variants | shipped | R-27 |
| [0019](0019-edge-backups-status-ai.md) | Off-site encrypted backups, status page, Workers AI | shipped* | R-28 |
| [0020](0020-brand-kit.md) | Brand kit as data + agent limits | shipped | R-29 |
| [0021](0021-cost-guardrails.md) | Cost guardrails: refuse instead of billing | shipped | R-30 |
| [0022](0022-radar-and-reporting-board.md) | Trend radar + a board that reports every feature | shipped | R-31 |
| [0023](0023-editorial-board-and-agent-guard.md) | Editorial board (two phases) + human-only agent gate | shipped | R-32 |
| [0024](0024-editable-identity-and-visual-spec.md) | Editable identity + `crm_visual_brief` enforcement | shipped | R-33 |
| [0025](0025-fast-agent-playbooks.md) | Four fast playbooks + `crm_inbox` / `crm_post_pack` | shipped | R-34 |
| [0026](0026-skill-library-ten-waves.md) | Skill library: 10 waves, 27 skills, 4 MCP servers | shipped | R-35 |
| [0027](0027-orchestration-layer.md) | Orchestration layer: one idea → execution pack + strategy skills | shipped | R-36 |
| [0028](0028-free-models-and-fallback.md) | Free models + measured fallback + token discipline | shipped | R-37 |
| [0029](0029-model-failover.md) | Model failover watcher + FreeRide evaluation | shipped | R-38 |

## Adding one

```bash
cp 0000-template.md 0005-my-feature.md
# fill Why / How / Verify / Limits, then:
python3 scripts/check_docs.py        # the same check CI runs
```

Rules enforced by `scripts/check_docs.py`:

- filename matches `NNNN-kebab-case.md` and the number is unique;
- the four headings (`## Why`, `## How`, `## Verify`, `## Limits`) exist and are non-empty;
- the page is linked from this index;
- any `R-NN` referenced here exists in [`../../ROADMAP.md`](../../ROADMAP.md);
- every path mentioned in `**Files:**` exists in the repository.
