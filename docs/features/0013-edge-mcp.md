# 0013 — edge-mcp: cloud tools that keep the phone light

- **Status:** shipped (code + local verification) · deploy pending an account
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.5.0
- **Roadmap:** R-22
- **Files:** `edge/src/index.js`, `edge/dev-server.mjs`, `edge/test/edge.test.js`, `edge/wrangler.toml`, `docs/EDGE-MCP.md`

## Why

The phone should own data, not CPU. Research (fetching a page, searching the web) is
network-bound and belongs on an edge worker: no secrets on the device, no battery cost, and
the phone keeps working when the network is slow. The MCP contract stays identical — PicoClaw
sees three more tools, not a new architecture.

## How

One stateless Worker speaking MCP over JSON-RPC (`POST /mcp`, bearer token):

| Tool | Behaviour |
|---|---|
| `edge_web_extract` | fetch with 8 s timeout, 1.5 MB byte cap, strip script/style/tags, return title + text (default 6,000 chars) |
| `edge_search` | Tavily → Brave → DuckDuckGo HTML, normalised to `{title,url,snippet}` |
| `edge_status` | version, tool names, which providers are configured, call count, uptime |

Deliberate choices:

- **No storage, no state** beyond a counter in memory: the phone remains the only source of
  truth, and there is nothing to sync.
- **Provider chain instead of one vendor**: Tavily (free monthly credits) and Brave (key) are
  both supported; DuckDuckGo is a fallback that measured **zero results from a datacenter
  IP**, so the tool returns an explicit `note` rather than pretending.
- **Byte caps and timeouts** because Workers Free gives 10 ms of CPU: waiting is free,
  parsing a 10 MB page is not.
- **Local adapter** (`dev-server.mjs`) runs the same handler on `node:http`, so the endpoint
  can be exercised and tested without a Cloudflare account.

## Verify

```bash
cd edge && npm test          # 13 tests, node:test, zero dependencies
EDGE_TOKEN=dev node dev-server.mjs
curl -s localhost:8787/health
curl -s -X POST localhost:8787/mcp -H 'Authorization: Bearer dev' \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"edge_web_extract","arguments":{"url":"https://example.com"}}}'
# title "Example Domain", 172 chars — real network fetch, measured
```

Bad token → 401; unknown method → JSON-RPC `-32601`; `file://` → error, not a fetch.

## Limits

- Not deployed: needs `wrangler login` + `secret put EDGE_TOKEN` (one browser step). Until
  then the tools exist only locally.
- DuckDuckGo fallback is unreliable from datacenters; a key is the real path.
- `edge_web_extract` is a text extractor, not a reader-mode engine: JS-rendered pages will
  come back thin. That is the free-plan trade-off, stated rather than hidden.
- PDFs are not parsed here (CPU); that is the Google Drive OCR path in
  `docs/CLOUD-PLACEMENT.md`.

## Links

- `docs/EDGE-MCP.md` (deploy + wiring)
- `docs/CLOUD-PLACEMENT.md`
