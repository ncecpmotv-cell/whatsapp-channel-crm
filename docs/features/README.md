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
