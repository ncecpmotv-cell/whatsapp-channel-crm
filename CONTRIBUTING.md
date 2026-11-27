# Contributing

Thanks for taking the time to improve this project. It is intentionally small: a Python stdlib bridge, a server-rendered Arabic UI, and two external binaries (GOWA, PicoClaw) that we integrate with rather than modify.

## Before you start

- Open an issue for anything larger than a bug fix, so we agree on the approach first.
- Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
- By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

1. **No new runtime dependency** unless the issue itself justifies it (impact, cost, alternative without the library). The phone has ~600 MB of usable RAM; that is the budget.
2. **No framework in the UI.** Forms must work without JavaScript; JS only enhances.
3. **Never invent a number or a claim.** Fixes ship with a measurement or a test output.
4. **Schema changes** need an issue and a migration plan; business rules (who may publish, what a state means) are not changed as a side effect.
5. **Security-sensitive paths** (`app.py` auth/CSRF/media, `service.py` publishing) need a test with the change.

## Workflow

```bash
git clone https://github.com/ncecpmotv-cell/whatsapp-channel-crm
cd whatsapp-channel-crm
git checkout -b feat/short-description

cd bridge && python3 -m unittest discover -s tests -v
cd .. && python3 scripts/e2e_local.py
BASE=http://127.0.0.1:8085 bash scripts/audit.sh   # needs a running instance
```

Commit style: imperative subject under ~72 chars, body explains *why* (not *what* — the diff says what). One logical change per commit.

Push, open a pull request, and fill in the template: what changed, how you verified it, and any trade-off you made.

## What makes a good PR here

- A UI change includes a 360 px screenshot (before/after) and keeps Lighthouse ≥ 95 on the page you touched.
- A behaviour change includes a failing test first, then the fix.
- A dependency proposal includes the size/RAM cost and the alternative you rejected.
- Docs stay true: if you change an endpoint or a flag, update `docs/API-MCP.md` / `docs/DEPLOY.md` in the same PR.

## Reporting bugs

Use the bug template. The most useful report contains: platform (Termux model / Linux distro), `crmctl status` output, the relevant lines from `var/log/*.log`, and what you expected instead.
