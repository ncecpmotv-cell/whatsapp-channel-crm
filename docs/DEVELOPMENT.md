# Development

## Layout

```
bridge/
  app.py        HTTP server: routing, auth, CSRF, media, multipart, static
  ui.py         server-rendered Arabic UI (tokens, pages, components)
  crm.py        SQLite schema + content/contact/deal model
  service.py    webhook handling, outbox worker, publishing, channel archive
  store.py      SQLite connection/WAL wrapper + outbox table
  gowa.py       GOWA REST client (Basic auth, multipart sends)
  mcp.py        MCP/JSON-RPC server and tool schemas
  config.py     env parsing
  static/       app.css, app.js, pico.min.css (+ .gz twins)
  tests/        unittest suite
scripts/
  install.sh    one-shot installer / upgrader
  uninstall.sh  stop and optionally purge
  audit.sh      19 static + HTTP checks
  build_static.py  regenerate app.css and the .gz assets
  e2e_local.py  end-to-end run against a fake GOWA
docs/           architecture, API, deployment, troubleshooting, audit
```

## Running locally

```bash
cd bridge
BRIDGE_TOKEN=dev-token BRIDGE_PORT=8085 CRM_DB_PATH=/tmp/crm.db \
  MEDIA_DIR=/tmp/crm-media STATIC_CACHE=/tmp/crm-static python3 app.py
```

The UI is at `http://127.0.0.1:8085/ui` (user: anything, password: `dev-token`). GOWA is optional for UI work; requests that need it fail into the outbox.

## Tests

```bash
cd bridge && python3 -m unittest discover -s tests -v   # 14 unit tests
cd .. && python3 scripts/e2e_local.py                    # 21 end-to-end checks
```

`e2e_local.py` starts a fake GOWA and a real bridge on a random port, then exercises: signed webhook, contact creation, UI auth, CSRF, draft creation, MCP handshake and tool calls, human approval, outbox publishing, archive import and counter updates. It is the regression net for behaviour, not just structure.

## Audit

```bash
BASE=http://127.0.0.1:8085 bash scripts/audit.sh
```

Checks compile, tests, e2e, hardcoded secrets, risky calls, public/private endpoints, token handling, CSP, inline scripts, asset versioning, media auth/traversal and CSRF rejection. Exit code is non-zero on any failure — wire it into CI or a pre-push hook.

## Editing the UI

1. Change `bridge/ui.py` (`CSS` for styles, the page functions for markup).
2. `python3 scripts/build_static.py` — regenerates `bridge/static/app.css`, `app.css.gz` and `app.js.gz`.
3. Reload. Asset URLs carry `?v=<content hash>`, so a browser can cache them for a week without going stale.

Rules of the UI code:

- Every mutation is a plain `<form method="post">`; JS only enhances (composer panel, skeletons, toasts, pull-to-refresh). The app must work with JS disabled.
- Escape everything with `esc()`; never interpolate a record field directly.
- Keep the design tokens (`--fs-*`, `--sp-*`, `--r-*`, colours) instead of ad-hoc values, and keep one gold accent per screen.
- Touch targets ≥ 44 px for primary controls; 360 px is the reference width.

## Conventions

- Python 3.12+, stdlib only for the runtime. No new dependency without a written justification (impact, cost, alternative).
- All SQL goes through `CrmClient`; parameters are bound, never formatted.
- Every new route needs: auth, CSRF (for POST under `/ui`), a test, and a line in `docs/API-MCP.md`.
- Commits: one logical change, imperative subject, body explaining *why*. Run the audit before pushing.
