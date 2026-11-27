/**
 * edge-mcp — a stateless MCP server on Cloudflare Workers.
 *
 * Tools
 *   edge_web_extract(url)      fetch a page, return readable text (no scripts/styles)
 *   edge_search(query, limit)  Brave when BRAVE_API_KEY is set, DuckDuckGo HTML otherwise
 *   edge_status()              what is configured, request counter, version
 *
 * Design rules
 *   - no storage: the phone owns the data, this Worker owns only CPU and secrets
 *   - every outbound call has a timeout and a byte cap (free plan = 10 ms CPU)
 *   - one bearer token; compare it in constant time; never echo it
 */

const VERSION = "0.1.0";
const MAX_BYTES = 1_500_000;
const FETCH_TIMEOUT_MS = 8000;

const TOOLS = [
  {
    name: "edge_web_extract",
    description: "Fetch a web page and return its readable text (scripts, styles and tags removed).",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "http(s) URL" },
        max_chars: { type: "integer", minimum: 500, maximum: 20000, default: 6000 },
      },
      required: ["url"],
    },
  },
  {
    name: "edge_search",
    description: "Web search headlines and snippets. Use it to research a topic before planning.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 10, default: 5 },
      },
      required: ["query"],
    },
  },
  {
    name: "edge_status",
    description: "Edge tool health: which providers are configured, request count, version.",
    inputSchema: { type: "object", properties: {} },
  },
];

const stats = { started: Date.now(), calls: 0 };

// ---------------------------------------------------------------- helpers
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a || "");
  const y = enc.encode(b || "");
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i += 1) diff |= x[i] ^ y[i];
  return diff === 0;
}

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

export function decodeEntities(text) {
  return text
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&([a-z]+);/gi, (m, name) => ENTITIES[name.toLowerCase()] ?? m);
}

/** HTML → readable text. Deliberately small: a Worker has 10 ms of CPU. */
export function htmlToText(html) {
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = decodeEntities((titleMatch ? titleMatch[1] : "").replace(/\s+/g, " ").trim());
  const text = html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<h[1-6][^>]*>/gi, "\n\n")
    .replace(/<\/(h[1-6])>/gi, "\n")
    .replace(/<(p|div|section|article|li|tr|br|ul|ol|blockquote)[^>]*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\n\s*\n\s*/g, "\n\n")
    .trim();
  return { title, text: decodeEntities(text) };
}

async function readCapped(response, cap = MAX_BYTES) {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let out = "";
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    out += decoder.decode(value, { stream: true });
    if (bytes >= cap) {
      await reader.cancel();
      break;
    }
  }
  out += decoder.decode();
  return out;
}

async function fetchText(url) {
  const parsed = new URL(url);
  if (!/^https?:$/.test(parsed.protocol)) throw new Error("only http(s) URLs are allowed");
  const response = await fetch(parsed.toString(), {
    redirect: "follow",
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: { "user-agent": "edge-mcp/0.1 (+phone-crm)", accept: "text/html,text/plain,*/*" },
  });
  if (!response.ok) throw new Error(`upstream answered ${response.status}`);
  return await readCapped(response);
}

// ---------------------------------------------------------------- tools
async function toolWebExtract(args, env) {
  const url = (args.url || "").trim();
  if (!url) throw new Error("url is required");
  const limit = Math.min(Math.max(Number(args.max_chars) || Number(env.MAX_CHARS) || 6000, 500), 20000);
  const raw = await fetchText(url);
  const { title, text } = htmlToText(raw);
  const clipped = text.slice(0, limit);
  return {
    url,
    title,
    chars: text.length,
    returned: clipped.length,
    truncated: text.length > clipped.length,
    text: clipped,
  };
}

export function parseDuckDuckGo(html, limit = 5) {
  const results = [];
  const re = /<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  const snippetRe = /class="result__snippet"[^>]*>([\s\S]*?)<\/a>/gi;
  const snippets = [...html.matchAll(snippetRe)].map((m) => decodeEntities(m[1].replace(/<[^>]+>/g, " ")).trim());
  let match;
  let index = 0;
  while ((match = re.exec(html)) && results.length < limit) {
    let href = match[1];
    const redirect = href.match(/uddg=([^&]+)/);
    if (redirect) href = decodeURIComponent(redirect[1]);
    const title = decodeEntities(match[2].replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
    if (!title || !href.startsWith("http")) {
      index += 1;
      continue;
    }
    results.push({ title, url: href, snippet: snippets[index] || "" });
    index += 1;
  }
  return results;
}

async function toolSearch(args, env) {
  const query = (args.query || "").trim();
  if (!query) throw new Error("query is required");
  const limit = Math.min(Math.max(Number(args.limit) || 5, 1), 10);

  if (env.TAVILY_API_KEY) {
    const response = await fetch("https://api.tavily.com/search", {
      method: "POST",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ api_key: env.TAVILY_API_KEY, query, max_results: limit,
                             search_depth: "basic", include_answer: false }),
    });
    if (!response.ok) throw new Error(`tavily answered ${response.status}`);
    const data = await response.json();
    return {
      provider: "tavily",
      results: (data.results || []).slice(0, limit).map((r) => ({
        title: r.title, url: r.url, snippet: r.content || "",
      })),
    };
  }

  if (env.BRAVE_API_KEY) {
    const url = new URL("https://api.search.brave.com/res/v1/web/search");
    url.searchParams.set("q", query);
    url.searchParams.set("count", String(limit));
    const response = await fetch(url, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      headers: { "x-subscription-token": env.BRAVE_API_KEY, accept: "application/json" },
    });
    if (!response.ok) throw new Error(`brave answered ${response.status}`);
    const data = await response.json();
    return {
      provider: "brave",
      results: (data.web?.results || []).slice(0, limit).map((r) => ({
        title: r.title,
        url: r.url,
        snippet: r.description || "",
      })),
    };
  }

  const response = await fetch("https://html.duckduckgo.com/html/", {
    method: "POST",
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      "user-agent": "Mozilla/5.0 (compatible; edge-mcp/0.1)",
    },
    body: new URLSearchParams({ q: query }).toString(),
  });
  if (!response.ok) throw new Error(`duckduckgo answered ${response.status}`);
  const html = await readCapped(response, 600_000);
  const results = parseDuckDuckGo(html, limit);
  return {
    provider: "duckduckgo",
    results,
    // Measured: DuckDuckGo answers empty from datacenter IPs; a key is the reliable path.
    note: results.length ? undefined : "no results — set BRAVE_API_KEY or TAVILY_API_KEY",
  };
}

function toolStatus(env) {
  return {
    ok: true,
    version: VERSION,
    tools: TOOLS.map((t) => t.name),
    providers: {
      brave: Boolean(env.BRAVE_API_KEY),
      tavily: Boolean(env.TAVILY_API_KEY),
      extract: true,
    },
    calls: stats.calls,
    uptime_seconds: Math.round((Date.now() - stats.started) / 1000),
  };
}

// ---------------------------------------------------------------- MCP
async function callTool(name, args, env) {
  stats.calls += 1;
  switch (name) {
    case "edge_web_extract":
      return await toolWebExtract(args || {}, env);
    case "edge_search":
      return await toolSearch(args || {}, env);
    case "edge_status":
      return toolStatus(env);
    default:
      throw new Error(`unknown tool: ${name}`);
  }
}

async function handleRpc(message, env) {
  const { id, method, params } = message;

  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "edge-mcp", version: VERSION },
      },
    };
  }
  if (method === "notifications/initialized") return null;
  if (method === "ping") return { jsonrpc: "2.0", id, result: {} };
  if (method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
  if (method === "tools/call") {
    const name = params?.name;
    try {
      const data = await callTool(name, params?.arguments, env);
      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], isError: false },
      };
    } catch (error) {
      return {
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: String(error.message || error) }], isError: true },
      };
    }
  }
  return { jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } };
}

export default {
  async fetch(request, env = {}) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") return new Response(null, { status: 204 });
    if (url.pathname === "/health" || url.pathname === "/") {
      return json({ ok: true, service: "edge-mcp", version: VERSION, tools: TOOLS.length });
    }
    if (url.pathname !== "/mcp") return json({ error: "not found" }, 404);
    if (request.method !== "POST") return json({ error: "use POST /mcp" }, 405);

    const auth = request.headers.get("authorization") || "";
    const token = auth.replace(/^Bearer\s+/i, "");
    if (!env.EDGE_TOKEN || !timingSafeEqual(token, env.EDGE_TOKEN)) {
      return json({ error: "unauthorized" }, 401);
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }, 400);
    }

    if (Array.isArray(payload)) {
      const replies = [];
      for (const item of payload) {
        const reply = await handleRpc(item, env);
        if (reply) replies.push(reply);
      }
      return replies.length ? json(replies) : new Response(null, { status: 202 });
    }

    const reply = await handleRpc(payload, env);
    if (!reply) return new Response(null, { status: 202 });
    return json(reply);
  },
};
