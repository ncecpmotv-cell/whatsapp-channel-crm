# Documentation

The documentation is the contract of this repository: **every behaviour has a page, every decision has a record, every roadmap item has an owner and a status.**

## Start here

| I want to… | Read |
|---|---|
| Install it on a phone or a server | [`DEPLOY.md`](DEPLOY.md) |
| Pair WhatsApp and find the channel JID | [`PAIRING-GOWA.md`](PAIRING-GOWA.md) |
| Connect the Telegram agent (PicoClaw) | [`TELEGRAM-AGENT.md`](TELEGRAM-AGENT.md) |
| Run the weekly content loop | [`CONTENT-PLAYBOOK.md`](CONTENT-PLAYBOOK.md) |
| Know what it is made of | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Call the API or the MCP tools | [`API-MCP.md`](API-MCP.md) |
| Work on the code | [`DEVELOPMENT.md`](DEVELOPMENT.md) |
| Fix something broken | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| Keep it alive on Android | [`ANDROID-BACKGROUND.md`](ANDROID-BACKGROUND.md) |
| Start/stop it on the phone after a reboot | [`termux-start.sh`](../scripts/termux-start.sh) · [`termux-infra-start.sh`](../scripts/termux-infra-start.sh) · [0006](features/0006-phone-start-script.md) |
| Use free tiers for search/images | [`INTEGRATIONS-FREE.md`](INTEGRATIONS-FREE.md) |
| See the PicoClaw config we ship | [`PICOCLAW.md`](PICOCLAW.md) |
| Know what is planned next | [`../ROADMAP.md`](../ROADMAP.md) |
| Understand a past decision | [`features/`](features/) |
| See the security/performance audit | [`AUDIT.md`](AUDIT.md) |

## The rules

1. **A feature is not done until it has a page in [`features/`](features/).** The page states *why* it exists, *how* it works, how it was verified, and which files it touched. Use [`features/0000-template.md`](features/0000-template.md).
2. **One feature, one number.** IDs are sequential and never reused; the page id is referenced from the PR, the commit body and the `CHANGELOG`.
3. **The roadmap is the only backlog.** An idea that is not in [`../ROADMAP.md`](../ROADMAP.md) does not exist; an item that ships moves to *Done* with a link to its feature page.
4. **Every page is linked twice:** from this hub, and from the code (module docstring or the route it documents). A page nobody can reach is a page that rots.
5. **`docs/` is English; the UI and owner-facing guides are Arabic.** Keep product copy in the language the user reads, keep engineering notes in the language developers read.

## Labels (GitHub)

| Label | Meaning |
|---|---|
| `type:feature` · `type:fix` · `type:docs` · `type:chore` | what kind of change |
| `area:content` · `area:mcp` · `area:ui` · `area:security` · `area:docs` · `area:installer` | where |
| `status:proposed` · `status:in-progress` · `status:blocked` · `status:done` | roadmap state |
| `needs-doc` | merged code without a `docs/features/` page — must be fixed before release |
| `good-first-issue` | scoped, low-risk, documented |

`scripts/check_docs.py` fails CI when a feature page is malformed or when `ROADMAP.md` links to a file that does not exist.

## Writing a feature page

```bash
cp docs/features/0000-template.md docs/features/0007-my-feature.md
```

- **Why** — the user problem, in two sentences, without jargon.
- **How** — the mechanism, files, and the one non-obvious decision.
- **Verify** — the exact commands and their output, not "tested manually".
- **Limits** — what it deliberately does not do.

Short is fine. A page that lies is worse than no page.
