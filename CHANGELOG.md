# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.16.0] — 2026-11-28

### Added

- **`crm_orchestrate`**: one idea in → intent (7 modes), compact numbers, angles, skill order,
  exact next tool calls, guards and a call budget. Deterministic; no model call.
- **`crm_capabilities`** + **`/ui/capabilities`**: skills, MCP servers, cron jobs, guards, last runs
  and cost caps in one screen.
- **`crm_runs`** table: every orchestrated request is recorded with its mode and step count.
- **Strategy skills**: `strategic-plan` (90-day arc), `strategic-analysis` (double-down/stop/
  experiment), `visibility-plan` (three discovery channels), `orchestrator` (the entry rule).
- `skill-router` and `editorial-board` now begin with `crm_orchestrate`, so the older playbooks are
  the second step of a routed flow instead of separate islands.
- **`context7`** MCP added (5 servers total); daily `orchestrator` cron at 07:30.
- `docs/MODELS.md`: free-tier models (Ollama Cloud, OpenRouter `:free`) and the seven token rules.

## [4.15.0] — 2026-11-28

### Added — the skill library (waves v4.5.0 → v4.14.0)

20 new Arabic playbooks on top of the existing 7 (27 total), each bounded to one model call —
or zero: `insight-interpreter`, `audience-persona`, `title-formulas`, `carousel-builder`,
`distribution-plan`, `crosspost-adapter`, `launch-calendar`, `series-planner`, `weekly-review`,
`retention-audit`, `ab-designer`, `offer-builder`, `fact-check-lite`, `source-log`,
`community-prompts`, `collab-pitch`, `voice-desk`, `incident-comms`, `skill-router`,
`metrics-glossary`.

- `skill-router` maps any request to one skill, so 27 playbooks do not collide in the prompt.
- `metrics-glossary` fixes interpretation: views are opens, reactions are not comments, one data
  point is not a trend.
- Two verified free remote MCP servers added: `cloudflare_docs` and `deepwiki` (four total with
  `crm` and `edge`). Search/extract MCPs were refused — they duplicate `tools.web` and the edge
  worker and cost context on every turn.
- `crm_update_channel_post` now merges `meta` instead of replacing it, so writing `sources` cannot
  wipe `visual_brief`.

## [4.4.0] — 2026-11-28

### Added

- **`crm_inbox`**: unread DMs with contact name, phone, org and stage in one query.
- **`crm_post_pack`**: one post with metrics, lint, plan slot, brand version, visual brief and the
  closest archived posts — 40 MCP tools.
- **Four skills**: `reply-desk` (classify + draft in one call, send only on an explicit word),
  `hook-lab` (8 hooks, local scoring, top 3), `repurpose` (one post → text series + 30s video +
  45s audio), `publish-runbook` (zero-model pre-flight and a one-line post-publish read).

## [4.3.0] — 2026-11-28

### Added

- **The identity is editable in the app**: `/ui/brand` is a validated form (palette pickers, fonts,
  formats, do/don't, logo policy, text-on-image rules, channel limits); every save bumps `version`
  and `updated_at`.
- **`crm_visual_brief(kind, topic)`**: the resolved visual spec — background/text/accent hex,
  format, fonts, logo policy, never-list and five imperative rules. 38 MCP tools.
- **Media lint**: `visual_brief_missing`, `brand_violation`, `off_palette`.
- `channel-brand` skill now orders the agent to fetch the spec before any visual draft, pass it
  through unchanged, and stop and ask when the identity is empty.

### Fixed

- The brand scan read its own `never` list and flagged every correct brief as a violation; the
  scan now covers descriptive fields only.

## [4.2.0] — 2026-11-28

### Added

- **Editorial board** (`picoclaw/skills/editorial-board`): four roles in one session, two phases —
  propose a plan (no bodies), then write drafts only after the owner approves. Measured live:
  plan `0eeb5710478f`, three items, `proposed`.
- **`crm_editorial_brief`**: one compact briefing (numbers, slots, gaps, angles, plan, brand)
  instead of five calls — 37 tools.
- **`AGENT_TOKEN`**: a second bearer token so the server can tell PicoClaw from the owner.

### Fixed

- **Approval bypass**: `crm_approve_plan`, `content_schedule` and `status: scheduled|published`
  updates now return `-32003 human-only` for agent tokens. The single-payload MCP path had to be
  fixed too — it forwarded no caller, so the first version of the guard was inert.
- **Weekly plan cron** was missing entirely (`cron list → No scheduled jobs`); recreated for
  Mondays 10:00 with a next run of 2026-11-30.
- **PicoClaw pointed at the retired preview worker**; its MCP «edge» server now uses
  `edge-mcp.ncecpmo.workers.dev` and the current token.
- **Skills unreadable to the agent**: `read_file` is workspace-restricted, so global skills are now
  also copied to `$PICOCLAW_HOME/workspace/skills`.
- **Update staleness, again**: codeload ignores query-string cache-busters on branch tarballs;
  `phone-update.sh` now resolves `main` to a commit SHA and downloads that immutable archive.

## [4.1.0] — 2026-11-28

### Added

- **Trend radar**: the edge fetches up to 10 RSS/Atom feeds every 30 minutes (rolling 500-item
  seen-set in KV, no model call), and the phone scores each headline against its own archive
  (`0.7 × novelty + 0.3 × recency`) before storing it. `crm_radar_scan`, `crm_angles`,
  `crm_angle_use` (draft only), `crm_angle_dismiss` — 36 MCP tools.
- **`/ui/radar`**: angle cards with «مسودة · المصدر · تجاهل», one model call per manual scan.
- **The board reports everything**: `/ui` became «لوحة القيادة» with average views, engagement rate,
  cadence, subscriber delta, best posting times (with sample size), content gaps, radar angles,
  failures, drafts, last backup and last heartbeat.
- A two-hourly background scan keeps headlines warm at zero AI cost.

### Notes

- `scripts/phone-update.sh` must keep its cache-buster: without it an update silently re-installs
  the previous commit (observed again — `radar.py` was missing after a "successful" update).

## [4.0.2] — 2026-11-28

### Added

- **Cost guardrails everywhere** (owner rule: the project never uses the paid tier): hard budgets
  for archive count (3), single archive (8MB), total storage (64MB, `507`) and Workers AI calls
  (40/day, `429`), all overridable from `wrangler.toml`.
- `GET /usage` and a live `/ui/edge` panel: backups kept/limit, MB used/budget, AI calls used/limit.
- `POST /backup/prune` re-applies retention by hand.

### Fixed

- **Retention now decides from R2's listing, not the KV index.** KV is eventually consistent and a
  stale read deleted the three newest archives while keeping the two oldest. Deletes are driven by
  `uploaded` timestamps from `R2.list`, and KV is rewritten as a cache afterwards.
- `budget()` read `env[maxTotalMb]` while the vars are `MAX_TOTAL_MB`; every limit silently fell
  back to its default. The mapping is explicit now, and a test proves `MAX_TOTAL_MB` is honoured.

## [4.0.1] — 2026-11-28

### Fixed

- **Cloudflare bot block**: `bridge/edge.py` now sends a real `User-Agent`; requests from
  Python urllib were answered with `403 error code: 1010`.
- **Vision model**: `llava-1.5-7b-hf` was deprecated on 2026-11-20. Caption now uses
  `llama-4-scout-17b-16e-instruct` with a data-URI image and returns structured
  `{description, hashtags}`; speech walks `whisper-large-v3-turbo` → `whisper` and reports
  which model answered.

### Fixed (phone → edge)

- **MIME for AI uploads**: `bridge/edge.py` sends `image/png`, `audio/mpeg`, … by extension, and
  the Worker sniffs PNG/JPEG/GIF/WEBP magic bytes when a client sends `application/octet-stream`.
  Workers AI rejected the image with `8006 expected image/* MIME type`.

### Deployed

- `https://edge-mcp.ncecpmo.workers.dev` on account `0476abbe…`: heartbeat, public status and
  both AI helpers are live. R2 is the one missing piece — the account must enable R2 in the
  dashboard (`10042`) before the backup binding can be added.

### Added

- `scripts/deploy-edge.sh` — credential check, bucket, KV, secrets, deploy, phone env lines.
- `scripts/phone-edge-env.sh` — writes `EDGE_URL`/`EDGE_TOKEN` into the env file the service
  actually reads and restarts it.

## [4.0.0] — 2026-11-28

### Added

- **Off-site encrypted backups**: the phone uploads each verified archive; the Worker encrypts
  it with AES-GCM into R2, keeps an index of 30 in KV, prunes older objects, and serves an
  authenticated download that decrypts byte-identically.
- **Heartbeat + public status page**: `/status` shows «يعمل / متوقف عن الإرسال», last beat
  age, counts and the last off-site archive — no secrets, no login.
- **Workers AI tools**: `crm_transcribe_audio` (whisper) and `crm_caption_image` (llava) call
  the edge with local file bytes; `/ui/edge` shows edge health, heartbeat age and off-site state.
- **Brand kit**: `crm_get_brand` / `crm_set_brand` (deep merge) with the channel palette, fonts,
  tone, do/don't lists and enforced limits; `/ui/brand` renders it and a `channel-brand` skill
  makes the agent obey it.
- 30 local MCP tools · 23 edge tests · 69 Python tests.

### Notes

- The Worker build is tested locally and in `node:test`, but **not deployed**: it needs the
  Cloudflare account that owns `edge-mcp` plus an R2 bucket and a KV namespace.

## [3.8.0] — 2026-11-27

### Added

- **Verified backups**: daily 03:00 archive (DB via sqlite backup + media), integrity-checked
  and row-counted on creation, rotated by mtime, with an offline `restore()` that clears stale
  WAL files.
- **Watchdog** every 5 minutes: WhatsApp logged out/unreachable, ≥3 failed publishes in 24 h,
  disk below 500 MB — deduplicated per hour, to bell + push.
- **Growth history**: `crm_channel_daily` snapshot + `channel_growth`, shown as «+N مشترك»
  on the channel page.
- **Daily brief** at 09:00: today's posts, drafts waiting for media, failures, plan state.
- **Proactive weekly plan**: PicoClaw cron `0 10 * * 4` analyses and saves a proposed plan;
  approval stays human.
- **`/ui/search`** over BM25, **`/ui/media`** library with usage, and **A/B variants**
  (`crm_create_variant`, `crm_variant_results`).

## [3.7.0] — 2026-11-27

### Added

- `crm_attach_media(post_id, path)` — attach the file PicoClaw downloaded from Telegram
  (or any local file under `ATTACH_ROOTS`), validate kind/size/extension, read image
  dimensions, and schedule at the plan slot when one exists.
- `crm_lint_post(post_id)` — pre-publish checks: empty content, missing media, near-duplicate
  of an earlier post (Jaccard ≥ 75 %), and a scheduled slot within 30 minutes of another post.
- `crm_best_slot(kind)` — best weekday/hour for a content type from the channel's own history,
  skipping slots already occupied; returns local time + epoch.

## [3.6.1] — 2026-11-27

### Fixed

- Approving a plan no longer schedules media posts that have no file. Image/video/audio/file
  items become drafts, are reported in  `needs_media`, and the plan page says «بانتظار الوسائط» until a file is attached. Found by the agent during the first real approval: two
  scheduled items would have failed at publish time.

## [3.6.0] — 2026-11-27

### Added

- **Plans as objects**: `crm_plans` / `crm_plan_items` with `crm_save_plan`, `crm_get_plan`
  and `crm_approve_plan` (idempotent; creates a draft per item and schedules it at `slot_at`).
  One plan per week; re-saving replaces items; an approved plan is immutable.
- **`/ui/plan`**: current week with item kinds, local slots, links to the created drafts and a
  single gold approval action; the Today page gains a plan card.
- **Sunday digest**: deterministic weekly message (posts, views, average, best type/slot,
  scheduled count, plan state, top opportunity) sent by a daemon thread at 20:00 local, at
  most once per six days, via PicoClaw's Telegram bot with a Termux fallback.
- Strategy skill now mandates: save the plan, present it from storage, and approve only on an
  explicit approval word.

## [3.5.2] — 2026-11-27

### Changed

- PicoClaw now searches natively: `tools.web.tavily` enabled with a Tavily key
  (1,000 queries/month), provider switched from `sogou` to `tavily`. Verified through the
  agent on the phone — three real results with links in ~25 s.
- Consequence recorded in STATE: with native `web_search` and `web_fetch`, the edge Worker's
  search/extract become a fallback; its remaining value is Google OAuth later, so the
  keep-or-unregister decision waits for that step.

## [3.5.1] — 2026-11-27

### Changed

- `edge-mcp` deployed and verified from the phone. The preview deployment's
  `403 cf-mitigated: challenge` disappeared after claiming the account; the same URL now
  answers from the mobile network (0.7 s extraction).
- Verified through the agent in one turn, two MCP servers: `edge_web_extract("example.com")`
  → "Example Domain" (172 chars) and `content_gaps(90)` → 22 posts, average 7.1.
- `semantic_search` gained light Arabic stemming (definite article + plurals): «المنتجات» now
  finds posts saying «منتجات».

## [3.5.0] — 2026-11-27

### Added

- `edge/`: a stateless Cloudflare Worker exposing MCP tools — `edge_web_extract`
  (8 s timeout, 1.5 MB cap, script/style stripping), `edge_search` (Tavily → Brave →
  DuckDuckGo fallback) and `edge_status`. One bearer token, constant-time compare, no
  storage; the phone stays the only source of truth.
- `edge/dev-server.mjs`: runs the same handler on node:http, so the MCP endpoint is
  testable without an account. 13 `node:test` tests, zero dependencies, added to CI.
- Measured: real extraction of example.com (title + 172 chars), 401 on a bad token,
  -32601 on unknown methods; DuckDuckGo returns zero results from a datacenter IP, so a
  search key is the reliable path and the tool says so.

### Notes

- Deployment is the one step that needs the owner: `wrangler login`, `secret put EDGE_TOKEN`,
  `deploy` — then `picoclaw mcp add edge …` (see `docs/EDGE-MCP.md`).

## [3.4.0] — 2026-11-27

### Added

- `content_gaps(days)`: repeated themes (bigrams) ranked against the channel average —
  under-used opportunities, saturated terms, cadence, longest gap, days since last post and
  per-type averages. Lexical, local, 1.2 ms on the production archive.
- `semantic_search(query)`: BM25 over titles and bodies, Arabic-normalised (hamza,
  taa marbuta, diacritics), ~1 ms, no embeddings and no network.
- MCP instructions now require `content_gaps` before a plan and a search before a new angle.
- `scripts/phone-update.sh`: update a phone install from the public repo without git;
  copies code and skills only, never `var/`, media or env files.

### Notes

- First cut of `content_gaps` ranked single-post terms; the live archive returned stopword
  noise (`الله،`, `باذن`). Themes now require ≥2 posts — the rule changed, not the wording.

## [3.3.0] — 2026-11-27

### Added

- `scripts/doctor.sh`: a read-only sweep of toolchain, runit units, the three health
  endpoints, WhatsApp pairing, MCP tool count, agent skills, the Tailscale node and serve
  entry, and push state. Detects the runit and `~/.whatsapp-crm` layouts; exits non-zero on
  a failure. Verified on the phone: 22 passed, 0 failed, 0 warnings.
- `docs/SETUP-FROM-ZERO.md` links the doctor as the post-install check.

## [3.2.0] — 2026-11-27

### Added

- Push notifications: `PushNotifier` delivers every bell event to Telegram (bot token +
  chat id) and/or Termux:API (`termux-notification`), off the request path and never raising.
  `/health` reports `push` state; `PUSH_EVENTS` chooses which events ring.
- The installer installs and wires **Tailscale**: static binaries for the machine's arch, a
  runit unit with `--state` and `--statedir`, a login link, and `--finish` to publish the UI
  with `tailscale serve --https=443`. New flags `--tailscale`, `--skip-tailscale`, `--finish`.

### Docs

- `docs/SETUP-FROM-ZERO.md`: the ordered zero-to-running guide (F-Droid prerequisites,
  installer steps, Tailscale loop and its failure modes, GOWA pairing, PicoClaw, push,
  health sweep, manual residue).
- Installer summary is now a checklist of what is done and the four human-only steps.

## [3.1.0] — 2026-11-27

### Added

- Content events now write to the bell: scheduled, published, publish failed, cancelled,
  restored and deleted — emitted by `CrmClient`, so UI, MCP and the scheduler all produce
  them. Publish/fail notifications carry dedupe keys so retries do not duplicate rows.
- Unread badge and notifications page verified end-to-end (0 → 1 after a delete).

## [3.0.3] — 2026-11-27

### Fixed

- In-app browsers (Telegram/Android WebView) post forms with `Origin: null`, which the guard
  rejected even though `Sec-Fetch-Site` said `same-origin`. A null Origin is now treated like
  a missing one — the CSRF token check still applies, and cross-site requests remain blocked.
  Diagnosed from the 403 detail added in 3.0.2 (`{"origin":"null", ...}`).

## [3.0.2] — 2026-11-27

### Fixed

- The 3.0.1 origin fix did not take effect in production: `PUBLIC_BASE_URL` lived in the env
  file, but the guard read `os.environ`, which never contains file-only keys. The values are
  now `Config` fields (`public_base_url`, `trusted_origins`, `allow_tailnet_domain`), read from
  the file like every other setting.
- `/health` exposes `origin_guard` booleans; the `crm` unit now has a log service, so a
  rejection logs the actual `Origin`/`Host`/`Sec-Fetch-Site` instead of failing silently.

### Fixed

- **Delete (and every form POST) failed behind `tailscale serve`** with
  `{"error": "cross-site request rejected"}`: the guard compared `Origin` to the `Host`
  the proxy rewrites. It now accepts the host the browser actually used —
  `Host`, `X-Forwarded-Host`, `PUBLIC_BASE_URL`, `TRUSTED_ORIGINS` — while a foreign Origin
  and `Sec-Fetch-Site: cross-site` are still rejected (9 new tests).
- Drafts can be deleted directly; scheduled/publishing posts still require cancel-then-delete
  and published posts remain immutable. The old rule forced cancel-first even for drafts,
  so the delete button appeared to do nothing.

## [3.0.0] — 2026-11-27

### Changed

- **The runtime is the phone.** GOWA, the CRM/MCP server and PicoClaw now run as runit
  services (`gowa`, `crm`, `picoclaw`); the server containers are retired
  (`docker compose down`, volumes kept for rollback).
- WhatsApp session migrated by copying `storages/` — same JID, no QR scan.
- `scripts/phone-start.sh` replaces the earlier launchers: ordered start with health waits,
  `status`/`stop`/`restart`, and the retired EspoCRM units kept down.

### Fixed

- PicoClaw on Termux: config paths pointed at `/data/workspace`; rewritten to the Termux home.
- PicoClaw's MCP entry pointed at the container port 8086; now 8085.
- Access: the device is a HUAWEI POT-LX1AF, so the Termux tailscale node is named `smartp`
  (the tailnet already had `pot-lx1af`). `tailscaled` now runs with `--statedir`; without it
  `tailscale serve` failed with `no TailscaleVarRoot`. UI: https://smartp.tail16a0c8.ts.net

## [2.1.2] — 2026-11-27

### Changed

- The phone is infrastructure-only by default: `scripts/termux-infra-start.sh` (removed in
  3.0.0, superseded by `scripts/phone-start.sh`) starts
  sshd, the reverse tunnel, tailscale and cron, and keeps the legacy EspoCRM/GOWA stack
  down (`--legacy` opts in). Boot script delegates to it, so there is one list of services.
- Disabled on the device: `gowa`, `bridge`, `mariadb`, `php-fpm`, `nginx` (down markers),
  freeing ~90 MB of RAM and removing an unpaired second WhatsApp session.

## [2.1.1] — 2026-11-27

### Fixed

- Reboot recovery on the phone: `scripts/termux-start.sh` (removed in 3.0.0, superseded by
  `scripts/phone-start.sh`) replaces a naive `start.sh`.
  It is idempotent, starts GOWA → CRM → PicoClaw with health waits, refuses to start a
  local gateway when the config points at a remote one, prints a status line per service
  and exits non-zero when something is down. `sh` invocations re-exec under bash.

## [2.1.0] — 2026-11-27

### Added

- `content-strategist` skill for PicoClaw: measure → diagnose → plan → draft, with a
  self-review checklist and hard prohibitions (never publish, never invent metrics).
- Installer copies `picoclaw/skills/` into the PicoClaw home on install and upgrade.

### Docs

- Documentation hub (`docs/README.md`), one page per feature (`docs/features/`), a roadmap
  with acceptance tests (`ROADMAP.md`), a free-tier integration guide and a PicoClaw config
  reference with a sanitized example.
- `scripts/check_docs.py` enforces the contract in CI (headings, index links, roadmap ids,
  file paths).

## [2.0.0] — 2026-11-27

First public release of the standalone CRM. It replaces the previous
EspoCRM-based bridge entirely.

### Added

- Analysis tools for the agent: `content_insights` (per-type averages, engagement,
  cadence, best/worst posts) and `posting_times` (weekday/hour performance).
- Content pipeline with four states (draft, approved/scheduled, published, cancelled),
  manual transitions, cancellation that keeps the record, and purge for cancelled items only.
- Arabic RTL mobile UI: progressive disclosure panels, filter chips, single primary action,
  numbered pagination, skeleton loading, toasts, pull-to-refresh, empty states.
- Outbox worker with retry backoff and permanent-failure reporting; scheduled posts publish
  themselves when due.
- Channel archive import (idempotent by message id), per-post metrics and daily series.
- MCP server with 14 tools so an agent can read the CRM, write drafts and propose times.
- Media support: text, image, video, audio, file and link; 20 MB cap; authenticated media route;
  image previews with reserved dimensions (no layout shift).
- One-shot installer that fetches the latest GOWA and PicoClaw releases, registers the MCP server,
  and writes a `crmctl` launcher plus runit/systemd integration.

### Security

- CSRF tokens on every form, cross-site request guard, per-IP login throttling.
- Strict CSP without inline scripts, `nosniff`, frame denial, no-referrer.
- Bearer-only control endpoints; query-string tokens removed.
- Upload extension whitelist; media route path validation.

### Performance

- gzip + `ETag`/304 for dynamic pages, hashed asset versions, 42 px mobile tab bar.
- Lighthouse mobile (360 px, 4× CPU, slow 4G): 100 performance, 100 accessibility,
  100 best practices, 100 SEO; LCP 0.9 s, CLS 0.

### Removed

- EspoCRM, MariaDB, PHP, nginx and the EspoCRM integration scripts.

[Unreleased]: https://github.com/ncecpmotv-cell/whatsapp-channel-crm/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ncecpmotv-cell/whatsapp-channel-crm/releases/tag/v2.0.0
