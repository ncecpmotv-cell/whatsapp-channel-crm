# Roadmap

The only backlog for this project. An item that is not here does not exist; an item that
ships moves to **Done** with a link to its [`docs/features/`](docs/features/) page and a
`CHANGELOG` entry.

**Rules of the road**

1. **Data before features.** Anything that claims to improve content must be explainable by
   `content_insights` / `posting_times` output.
2. **No new runtime dependency on the phone.** A feature that needs one ships as an optional
   integration, not in the core path.
3. **Every item names its acceptance test.** "Looks better" is not acceptance.
4. **One item in `Now` at a time.** Parallel work happens in `Next` only when the files do
   not overlap.

Legend: **S** = one sitting (≤ 1 h) · **M** = a day · **L** = a week.

---

## Now — v2.1 "Agent that plans with data"

### R-05 — Content Strategist skill pack  ·  S  ·  `status:done` ✅
A skill for PicoClaw that encodes the weekly loop (measure → diagnose → plan → draft) so the
agent follows the same method every time instead of improvising.

- **Acceptance:** the skill is installed by `scripts/install.sh`, `picoclaw skills list`
  shows it, and a scripted prompt produces a plan whose items cite `content_insights`
  numbers.
- **Files:** `picoclaw/skills/content-strategist/SKILL.md`, `scripts/install.sh`,
  `docs/features/0005-content-strategist-skill.md`.

### R-06 — Free search adapter (Exa or Firecrawl)  ·  S  ·  `status:proposed`
Read-only research so topics are grounded in current sources, not model memory.

- **Acceptance:** with a free-tier key, `picoclaw mcp test exa` exits 0 and the agent quotes
  a source URL in a plan.
- **Blocked by:** owner key. Fallback: Firecrawl (1,000 credits/month free).

### R-07 — Plan → batch drafts  ·  M  ·  `status:proposed`
One MCP call that turns a structured plan (array of items) into N drafts with titles, bodies,
types and proposed times, all in `draft`.

- **Acceptance:** a 4-item plan creates exactly 4 drafts, none `scheduled`, and a re-run with
  the same plan id does not duplicate (idempotency key).
- **Why not now:** needs an idempotency column; schema change requires its own feature page.

---

## Next — v2.2 "Closer to the publishing decision"

| ID | Item | Effort | Why now |
|---|---|---|---|
| R-08 | **Weekly digest to Telegram** — a Monday 08:00 job that posts last week's numbers and the top/bottom posts | S | closes the loop without opening the UI |
| R-09 | **A/B variants** — two drafts for one slot, pick the winner by early views | M | turns `content_insights` into a decision, not a report |
| R-10 | **Multi-channel** — `NEWSLETTER_JIDS` already plural; make the UI/agent address a channel explicitly | M | the schema supports it; the UI assumes one |
| R-11 | **CSV export** of posts + metrics | S | owners want Excel; no API needed |

## Later — v3 "Beyond one phone"

| ID | Item | Notes |
|---|---|---|
| R-12 | Telegram channel as a second publishing target | needs a Telegram bot with channel admin rights; same approval model |
| R-13 | Auto-schedule to the best slot | only after R-09 has enough data; must stay a *proposal* |
| R-14 | Team roles (reviewer vs publisher) | replaces the shared token; needs a real user table |

---

## Done

| ID | Item | Version | Record |
|---|---|---|---|
| R-01 | Content pipeline with human approval | v2.0.0 | [0001](docs/features/0001-content-pipeline.md) |
| R-02 | Authenticated media + previews + CLS fix | v2.0.0 | [0003](docs/features/0003-media-and-security.md) |
| R-03 | `content_insights` + `posting_times` | v2.1.0 | [0002](docs/features/0002-mcp-analysis-tools.md) |
| R-04 | One-command installer | v2.0.0 | [0004](docs/features/0004-one-shot-installer.md) |
| R-05 | Content Strategist skill pack | v2.1.0 | [0005](docs/features/0005-content-strategist-skill.md) |
| R-15 | Phone start script: idempotent, ordered, honest | v2.1.1 | [0006](docs/features/0006-phone-start-script.md) |
| R-16 | Run the whole stack on the phone (no server containers) | v3.0.0 | [0007](docs/features/0007-stack-on-the-phone.md) |
| R-17 | Notifications for every content event | v3.1.0 | [0008](docs/features/0008-notifications.md) |

---

## How an item moves

1. Open an issue with the roadmap id in the title (`R-07: plan → batch drafts`) and the
   `status:proposed` label.
2. On start: label `status:in-progress`, create `docs/features/000N-<slug>.md` from the
   template **with the Verify section written first** (what will prove it).
3. On merge: label `status:done`, add the row to **Done**, add a `CHANGELOG` entry.
4. `scripts/check_docs.py` (CI) rejects a feature page whose roadmap id is missing here, or
   a roadmap link that points at a file that does not exist.
