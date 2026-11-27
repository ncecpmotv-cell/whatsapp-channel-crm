import assert from "node:assert/strict";
import test from "node:test";

import worker, { htmlToText, decodeEntities, parseDuckDuckGo } from "../src/index.js";

const ENV = { EDGE_TOKEN: "secret", MAX_CHARS: "6000" };

function rpc(payload, token = "secret") {
  return new Request("http://edge.test/mcp", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

async function call(payload, token = "secret") {
  const response = await worker.fetch(rpc(payload, token), ENV);
  return { status: response.status, body: await response.json() };
}

test("rejects a request without the bearer token", async () => {
  const response = await worker.fetch(
    new Request("http://edge.test/mcp", { method: "POST", body: "{}" }), ENV);
  assert.equal(response.status, 401);
});

test("rejects a wrong token", async () => {
  const { status } = await call({ jsonrpc: "2.0", id: 1, method: "initialize" }, "nope");
  assert.equal(status, 401);
});

test("initialize handshake", async () => {
  const { body } = await call({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
  assert.equal(body.result.protocolVersion, "2024-11-05");
  assert.equal(body.result.serverInfo.name, "edge-mcp");
});

test("tools/list exposes the three tools", async () => {
  const { body } = await call({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  const names = body.result.tools.map((t) => t.name).sort();
  assert.deepEqual(names, ["edge_search", "edge_status", "edge_web_extract"]);
});

test("edge_status reports configuration without leaking the token", async () => {
  const { body } = await call({
    jsonrpc: "2.0", id: 3, method: "tools/call",
    params: { name: "edge_status", arguments: {} },
  });
  const data = JSON.parse(body.result.content[0].text);
  assert.equal(data.ok, true);
  assert.equal(data.providers.brave, false);
  assert.ok(!JSON.stringify(data).includes("secret"));
});

test("htmlToText drops scripts and keeps the title", () => {
  const html = `<html><head><title>عنوان الصفحة</title>
    <style>body{color:red}</style></head>
    <body><script>alert("x")</script><h1>فكرة</h1><p>نص &amp; تفاصيل</p></body></html>`;
  const { title, text } = htmlToText(html);
  assert.equal(title, "عنوان الصفحة");
  assert.match(text, /فكرة/);
  assert.match(text, /نص & تفاصيل/);
  assert.doesNotMatch(text, /alert|color:red/);
});

test("decodeEntities handles named and numeric entities", () => {
  assert.equal(decodeEntities("a &amp; b &#39;c&#x27;"), "a & b 'c'");
});

test("edge_web_extract fetches and truncates", async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    "<html><head><title>T</title></head><body><p>" + "كلمة ".repeat(200) + "</p></body></html>",
    { status: 200 });
  try {
    const { body } = await call({
      jsonrpc: "2.0", id: 4, method: "tools/call",
      params: { name: "edge_web_extract", arguments: { url: "https://example.com", max_chars: 500 } },
    });
    const data = JSON.parse(body.result.content[0].text);
    assert.equal(data.title, "T");
    assert.equal(data.returned, 500);   // the schema floor is 500 chars
    assert.equal(data.truncated, true);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("edge_web_extract refuses non-http schemes", async () => {
  const { body } = await call({
    jsonrpc: "2.0", id: 5, method: "tools/call",
    params: { name: "edge_web_extract", arguments: { url: "file:///etc/passwd" } },
  });
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /http/i);
});

test("parseDuckDuckGo unwraps redirect links and pairs snippets", () => {
  const html = `
    <a rel="nofollow" class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x">الأول</a>
    <a class="result__snippet" href="#">مقتطف أول</a>
    <a rel="nofollow" class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb">الثاني</a>
    <a class="result__snippet" href="#">مقتطف ثان</a>`;
  const results = parseDuckDuckGo(html, 5);
  assert.equal(results.length, 2);
  assert.equal(results[0].url, "https://example.com/a");
  assert.equal(results[0].title, "الأول");
  assert.equal(results[0].snippet, "مقتطف أول");
});

test("edge_search uses duckduckgo when no brave key is set", async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    `<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fx.test%2F1">نتيجة</a>
     <a class="result__snippet" href="#">مقتطف</a>`, { status: 200 });
  try {
    const { body } = await call({
      jsonrpc: "2.0", id: 6, method: "tools/call",
      params: { name: "edge_search", arguments: { query: "تصوير المنتجات", limit: 3 } },
    });
    const data = JSON.parse(body.result.content[0].text);
    assert.equal(data.provider, "duckduckgo");
    assert.equal(data.results[0].url, "https://x.test/1");
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("edge_search prefers tavily when its key is set", async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.match(String(url), /api\.tavily\.com/);
    assert.match(init.body, /api_key/);
    return new Response(JSON.stringify({ results: [
      { title: "T", url: "https://t.test", content: "c" }] }), { status: 200 });
  };
  try {
    const response = await worker.fetch(
      new Request("http://edge.test/mcp", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer secret" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 8, method: "tools/call",
          params: { name: "edge_search", arguments: { query: "x" } } }),
      }),
      { EDGE_TOKEN: "secret", TAVILY_API_KEY: "tvly" });
    const body = await response.json();
    const data = JSON.parse(body.result.content[0].text);
    assert.equal(data.provider, "tavily");
    assert.equal(data.results[0].url, "https://t.test");
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("unknown methods answer -32601 instead of crashing", async () => {
  const { body } = await call({ jsonrpc: "2.0", id: 7, method: "resources/list" });
  assert.equal(body.error.code, -32601);
});
