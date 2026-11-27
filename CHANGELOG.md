# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
