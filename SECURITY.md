# Security policy

## Reporting a vulnerability

Open a **private** security advisory on GitHub (Security → Advisories → “Report a vulnerability”), or email the maintainer listed on the profile. Please do not open a public issue for anything exploitable.

Include: affected endpoint or file, a reproduction (curl or a short script), the impact you believe it has, and whether the instance was exposed beyond `127.0.0.1`.

Expect an acknowledgement within 72 hours. Fixes are released as a patch commit on `main` with a `CHANGELOG` entry; you will be credited unless you ask otherwise.

## Two tokens, two levels of trust (v4.2.0)

`BRIDGE_TOKEN` is the owner's token: the UI's Basic password and the token a human MCP client
uses. `AGENT_TOKEN` is what PicoClaw carries. The MCP server compares the presented bearer with
both, marks the request `agent` or `human`, and refuses (`-32003`) `crm_approve_plan`,
`content_schedule` and any update that would set `scheduled`/`published` when the caller is an
agent. Leave `AGENT_TOKEN` empty only on a machine with no agent connected — the gate is inert.

## Threat model

The intended deployment is a personal instance:

- bound to `127.0.0.1`, reached through a private tailnet (Tailscale) or an SSH tunnel;
- one human owner who holds `BRIDGE_TOKEN`;
- one WhatsApp account, paired through GOWA.

**Out of scope:** multi-tenant hosting, public internet exposure, hostile users on the same host, and physical access to the device.

## Controls in place

| Area | Control |
|---|---|
| UI authentication | HTTP Basic; password = `BRIDGE_TOKEN`; compared with `hmac.compare_digest` |
| Brute force | 10 failed attempts per IP / 5 min → `429` + `Retry-After` |
| CSRF | per-deployment token embedded in every form, `Sec-Fetch-Site`/`Origin` guard |
| Session transport | token never accepted in the query string (it would land in logs/history) |
| XSS | every rendered value passes `esc()`; CSP `script-src 'self'`, no inline scripts |
| Headers | CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` |
| Webhook | HMAC-SHA256 over the raw body (`X-Hub-Signature-256`), de-duplication by message id |
| MCP / control API | bearer token, JSON-RPC only on POST |
| Uploads | 20 MB cap, extension whitelist per content type, random filenames, never executed |
| Media | authenticated route with a strict filename pattern (no traversal) |
| SQL | bound parameters only; column lists come from internal whitelists |
| Secrets at rest | `etc/*.env` and `picoclaw/config.json` are mode 600; the repo ships none |

## Known limitations

- **Basic auth over loopback/Tailscale only.** Terminate TLS at Tailscale; do not port-forward this app.
- **Single shared token** — no per-user accounts or audit trail of *who* did what. It is a personal tool.
- **Rate limiting is in-memory** — a restart clears it; a determined attacker on the host is out of scope.
- **The agent can read the CRM and write drafts.** Publishing requires a human unless you explicitly set `AGENT_CAN_PUBLISH=1`; if you do, you own the consequence.

## Hardening checklist for a new deployment

1. `crmctl status` shows all three processes up; nothing listens on `0.0.0.0` (`ss -ltnp`).
2. `etc/crm.env` is mode 600 and `BRIDGE_TOKEN` is not reused anywhere else.
3. UI reachable only through `tailscale serve` (or an SSH tunnel).
4. `bash scripts/audit.sh` passes 19/19.
5. Backups exist and have been restored at least once.
