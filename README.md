# WhatsApp Channel CRM

**A single-process CRM for a WhatsApp Channel — content pipeline, contacts, deals and channel metrics — running on one phone, one SQLite file, one port.**

Built for people who publish from a phone: it turns a WhatsApp Channel into a small editorial desk with an approval workflow, and exposes the whole thing to an AI agent over MCP.

[![CI](https://github.com/ncecpmotv-cell/whatsapp-channel-crm/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-brightgreen.svg)](https://www.python.org/)

---

## Why

Most CRMs assume a server, a database and a team. A channel owner needs four things:

1. **Write and approve posts** without CMS sprawl: `draft → approved/scheduled → published | cancelled`.
2. **See what the channel did**: views, forwards, reactions per post, daily series.
3. **Keep the leads** that arrive in DMs as contacts and deals.
4. **Let an agent help** — but never publish on its own.

This project does exactly that, and nothing else. No PHP, no MariaDB, no Node runtime, no container on the device. Roughly **30 MB of RAM** for the CRM process; the UI is server-rendered Arabic RTL HTML with a 3.5 KB progressive-enhancement script.

## What you get

| Piece | Role |
|---|---|
| **CRM bridge** (Python stdlib + SQLite) | Content pipeline, contacts, deals, metrics, Arabic web UI, MCP server |
| **[GOWA](https://github.com/aldinokemal/go-whatsapp-web-multidevice)** | Pairs with WhatsApp, sends channel posts, delivers inbound DMs |
| **[PicoClaw](https://github.com/sipeed/picoclaw)** | Personal agent runtime; talks to the CRM through MCP tools |
| **Tailscale** (optional) | Private HTTPS access to the UI from your phone or laptop |

```
PicoClaw ──MCP :8085/mcp──┐
                          ├── CRM bridge (Python + SQLite) ── crm.db + media/
GOWA :3000 ──webhook──────┘        └── Arabic UI :8085/ui
```

## Install (one script)

```bash
git clone https://github.com/ncecpmotv-cell/whatsapp-channel-crm
cd whatsapp-channel-crm
bash scripts/install.sh
```

The installer detects Termux or Linux, downloads the **latest** GOWA and PicoClaw releases for your architecture, generates secrets, registers the CRM as an MCP server inside PicoClaw, writes a launcher, and starts everything.

```bash
~/.whatsapp-crm/bin/crmctl status     # crm / gowa / pico
bash scripts/install.sh --qr          # print the WhatsApp pairing QR
bash scripts/install.sh --upgrade     # pull the latest GOWA, PicoClaw and CRM
```

Open `http://127.0.0.1:8085/ui` — any username, password = `BRIDGE_TOKEN` from `~/.whatsapp-crm/etc/crm.env`.

Options, Tailscale, systemd/runit and uninstall: [`docs/DEPLOY.md`](docs/DEPLOY.md).

## The content workflow

```
draft ──► approved & scheduled ──► publishing ──► published
  │                 │
  └──── cancelled ◄─┘   (kept in the archive; purge only from cancelled)
```

- The **agent can write and propose times**, but publishing stays a human decision (`AGENT_CAN_PUBLISH=0` by default).
- Publishing is queued in an outbox with retries and permanent-failure reporting, so a network blip does not lose a post.
- Published posts are immutable in the UI; scheduled posts can be cancelled or rescheduled before they go out.
- Types: text, image, video, audio, file, link. Polls are rejected with a clear message (WhatsApp Channels do not support them).

## Security posture

- Bind to `127.0.0.1`; expose over Tailscale, never the public internet.
- UI: HTTP Basic (`BRIDGE_TOKEN`), CSRF token on every form, `Sec-Fetch-Site`/`Origin` guard, per-IP auth throttling.
- Strict CSP, `nosniff`, frame denial, no inline scripts, hashed asset versions.
- Webhook requires an HMAC-SHA256 signature; MCP and control endpoints require a bearer token.
- Uploads: 20 MB cap, per-type extension whitelist, media served only through an authenticated, path-validated route.

Report vulnerabilities per [`SECURITY.md`](SECURITY.md).

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Processes, ports, data model, request flows, decisions |
| [`docs/API-MCP.md`](docs/API-MCP.md) | HTTP endpoints and all MCP tools with examples |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Install, upgrade, Termux, systemd, Tailscale, backup |
| [`docs/PAIRING-GOWA.md`](docs/PAIRING-GOWA.md) | اقتران واتساب خطوة بخطوة، وماذا تفعل عند الانقطاع |
| [`docs/TELEGRAM-AGENT.md`](docs/TELEGRAM-AGENT.md) | ربط بوت تليجرام بالوكيل: التوكن، الصلاحيات، الأوامر |
| [`docs/CONTENT-PLAYBOOK.md`](docs/CONTENT-PLAYBOOK.md) | دورة العمل: تحليل → خطة → مراجعة بشرية → نشر |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Tests, audit, static assets, conventions |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | The failures that actually happen |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Security and performance audit (Arabic) |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |

## Development

```bash
cd bridge && python3 -m unittest discover -s tests -v     # unit tests
cd .. && python3 scripts/e2e_local.py                      # end-to-end (fake GOWA)
BASE=http://127.0.0.1:8085 bash scripts/audit.sh           # 19 static/security checks
```

Measured with Lighthouse mobile (360 px, 4× CPU, slow 4G): **100 performance · 100 accessibility · 100 best practices · 100 SEO**, LCP 0.9 s, CLS 0.

## Contributing

Issues and pull requests are welcome — read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT — see [`LICENSE`](LICENSE).

---

## بالعربية

نظام CRM خفيف لقناة واتساب يعمل كله على الجوال: إدارة محتوى بمراحل (مسودة → معتمد ومجدول → منشور/ملغى)، عملاء وفرص، وقياسات القناة، بواجهة عربية RTL، مع وكيل ذكاء (PicoClaw) يتصل به عبر MCP.

```bash
git clone https://github.com/ncecpmotv-cell/whatsapp-channel-crm
cd whatsapp-channel-crm && bash scripts/install.sh
```

- التنزيل يجلب أحدث إصدارات GOWA وPicoClaw، ويولّد الأسرار، ويشغّل الخدمات.
- `~/.whatsapp-crm/bin/crmctl status` للحالة، و`bash scripts/install.sh --qr` لمسح رمز الاقتران.
- النشر قرار بشري دائمًا؛ الوكيل يكتب ويقترح فقط (يُغيّر بـ`AGENT_CAN_PUBLISH=1`).
- الوصول عبر Tailscale فقط: `tailscale serve --bg --https=443 http://127.0.0.1:8085`.
- الاقتران: [`docs/PAIRING-GOWA.md`](docs/PAIRING-GOWA.md) · وكيل تليجرام: [`docs/TELEGRAM-AGENT.md`](docs/TELEGRAM-AGENT.md) · دورة المحتوى: [`docs/CONTENT-PLAYBOOK.md`](docs/CONTENT-PLAYBOOK.md).

الدليل الكامل: [`docs/DEPLOY.md`](docs/DEPLOY.md) · تقرير التدقيق: [`docs/AUDIT.md`](docs/AUDIT.md).
