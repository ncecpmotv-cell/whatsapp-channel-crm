# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
